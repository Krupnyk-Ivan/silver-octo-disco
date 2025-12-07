using Microsoft.AspNetCore.Mvc;
using QuizService.Data;
using QuizService.Models;
using QuizService.Services;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;

namespace QuizService.Controllers
{
    [ApiController]
    [Route("api/quiz/attempts")]
    public class AttemptsController : ControllerBase
    {
        private readonly QuizDbContext _db;
            private readonly ILogger<AttemptsController> _logger;
            private readonly RabbitMqProducer _producer;

            public AttemptsController(QuizDbContext db, ILogger<AttemptsController> logger, RabbitMqProducer producer)
            {
                _db = db;
                _logger = logger;
                _producer = producer;
            }

        public class CreateAttemptDto
        {
            public string StudentId { get; set; } = string.Empty;
            public int DurationMinutes { get; set; } = 5;
        }

        [HttpPost]
        public async Task<IActionResult> Create([FromBody] CreateAttemptDto dto)
        {
            var a = new QuizAttempt
            {
                Id = Guid.NewGuid(),
                StudentId = dto.StudentId,
                StartedAt = DateTime.UtcNow,
                DurationMinutes = dto.DurationMinutes
            };
            _db.QuizAttempts.Add(a);
            await _db.SaveChangesAsync();
            return CreatedAtAction(nameof(Get), new { id = a.Id }, a);
        }

        [HttpGet("{id:guid}")]
        public async Task<IActionResult> Get(Guid id)
        {
            var a = await _db.QuizAttempts.FirstOrDefaultAsync(x => x.Id == id);
            if (a == null) return NotFound();
            return Ok(a);
        }

        public class AnswerDto
        {
            public Guid QuestionId { get; set; }
            public string AnswerText { get; set; } = string.Empty;
        }

        public class SubmitAttemptDto
        {
            public List<AnswerDto> Answers { get; set; } = new List<AnswerDto>();
        }

        [HttpPost("{id:guid}/submit")]
        public async Task<IActionResult> Submit(Guid id, [FromBody] SubmitAttemptDto dto)
        {
            var attempt = await _db.QuizAttempts.FirstOrDefaultAsync(x => x.Id == id);
            if (attempt == null) return NotFound();

            var now = DateTime.UtcNow;
            var elapsed = now - attempt.StartedAt;
            if (elapsed.TotalSeconds > (attempt.DurationMinutes * 60) + 5) // 5s grace
            {
                return BadRequest(new { error = "Attempt expired" });
            }

            // Load questions for grading
            var qIds = dto.Answers.Select(a => a.QuestionId).ToList();
            var questions = await _db.Questions.Where(q => qIds.Contains(q.Id)).ToListAsync();

            // Load recent knowledge items to include as context (server-side prompt)
            var knowledge = await _db.KnowledgeItems.OrderByDescending(k => k.CreatedAt).Take(5).ToListAsync();

            // Build a structured prompt that the AI can consume directly
            var sb = new System.Text.StringBuilder();
            sb.AppendLine("Ви — інструктор з надання першої допомоги. Оцініть відповіді студента і поверніть JSON з полями: score (0-100), feedback, reasoning.");
            sb.AppendLine();
            for (int i = 0; i < dto.Answers.Count; i++)
            {
                var a = dto.Answers[i];
                var q = questions.FirstOrDefault(x => x.Id == a.QuestionId);
                sb.AppendLine($"Question {i+1}: {q?.Text ?? string.Empty}");
                sb.AppendLine($"Student Answer: {a.AnswerText}");
                sb.AppendLine();
            }
            if (knowledge.Any())
            {
                sb.AppendLine("Context (knowledge items):");
                foreach (var k in knowledge)
                {
                    sb.AppendLine($"- {k.Title}: {k.Content}");
                }
                sb.AppendLine();
            }
            var attemptPrompt = sb.ToString();
            attempt.PromptUsed = attemptPrompt;

            int total = dto.Answers.Count;
            int correct = 0;

            foreach (var a in dto.Answers)
            {
                var q = questions.FirstOrDefault(x => x.Id == a.QuestionId);
                var submission = new QuizSubmission
                {
                    Id = Guid.NewGuid(),
                    StudentId = attempt.StudentId,
                    Question = q?.Text ?? string.Empty,
                    AnswerText = a.AnswerText,
                    Status = "Pending",
                    QuestionId = a.QuestionId,
                    AttemptId = attempt.Id
                };
                _db.QuizSubmissions.Add(submission);

                // Publish submission.created with prompt/context so ai-service can evaluate without extra HTTP calls
                try
                {
                    var payload = new
                    {
                        Id = submission.Id,
                        StudentId = submission.StudentId,
                        Question = submission.Question,
                        AnswerText = submission.AnswerText,
                        Status = submission.Status,
                        AttemptId = submission.AttemptId,
                        AttemptPrompt = attemptPrompt
                    };
                    _producer.Publish("med_events", "submission.created", JsonSerializer.Serialize(payload));
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to publish submission.created for submission {id}", submission.Id);
                }

                if (q != null && !string.IsNullOrEmpty(q.CorrectAnswer))
                {
                    if (string.Equals(q.CorrectAnswer.Trim(), a.AnswerText.Trim(), StringComparison.OrdinalIgnoreCase))
                    {
                        correct += 1;
                    }
                }
            }

            // finalize attempt
            attempt.CompletedAt = now;
            attempt.Score = total > 0 ? (int)Math.Round((double)correct / total * 100) : 0;

            await _db.SaveChangesAsync();

            return Ok(new { attemptId = attempt.Id, score = attempt.Score, total, correct });
        }
    }
}
