using Microsoft.AspNetCore.Mvc;
using QuizService.Data;
using QuizService.Models;
using QuizService.Services;
using QuizService.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using System.Linq;

namespace QuizService.Controllers
{
    [ApiController]
    [Route("api/quiz")]
    public class QuizController : ControllerBase
    {
        private readonly QuizDbContext _db;
        private readonly RabbitMqProducer _producer;
        private readonly ILogger<QuizController> _logger;

        public QuizController(QuizDbContext db, RabbitMqProducer producer, ILogger<QuizController> logger)
        {
            _db = db;
            _producer = producer;
            _logger = logger;
        }

        public class SubmitDto
        {
            public string StudentId { get; set; } = string.Empty;
            public string Question { get; set; } = string.Empty;
            public string AnswerText { get; set; } = string.Empty;
        }

        [HttpPost("submit")]
        public async Task<IActionResult> Submit([FromBody] SubmitDto dto)
        {
            var submission = new QuizSubmission
            {
                Id = Guid.NewGuid(),
                StudentId = dto.StudentId,
                Question = dto.Question,
                AnswerText = dto.AnswerText,
                Status = "Pending"
            };

            _db.QuizSubmissions.Add(submission);
            await _db.SaveChangesAsync();

            var payload = new
            {
                Id = submission.Id,
                StudentId = submission.StudentId,
                Question = submission.Question,
                AnswerText = submission.AnswerText,
                Status = submission.Status
            };

            try
            {
                _producer.Publish("med_events", "submission.created", System.Text.Json.JsonSerializer.Serialize(payload));
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed publishing submission.created event");
            }

            // No SignalR/SSE action here - UI polls for updates via `/api/quiz/{id}`

            return CreatedAtAction(nameof(Get), new { id = submission.Id }, submission);
        }

        [HttpGet("{id:guid}")]
        public async Task<IActionResult> Get(Guid id)
        {
            var s = await _db.QuizSubmissions.FirstOrDefaultAsync(x => x.Id == id);
            if (s == null) return NotFound();
            return Ok(s);
        }

        // GET /api/quiz
        // Returns all submissions. Useful for listing recent questions in the UI.
        [HttpGet]
        public async Task<IActionResult> List()
        {
            var list = await _db.QuizSubmissions
                .OrderByDescending(x => x.Id)
                .ToListAsync();
            return Ok(list);
        }

        public class ReviewDto
        {
            public int Score { get; set; }
            public string? Status { get; set; }
            public string? Feedback { get; set; }
        }

        [HttpPost("{id:guid}/review")]
        public async Task<IActionResult> Review(Guid id, [FromBody] ReviewDto dto)
        {
            var s = await _db.QuizSubmissions.FirstOrDefaultAsync(x => x.Id == id);
            if (s == null) return NotFound();

            s.Score = dto.Score;
            if (!string.IsNullOrEmpty(dto.Status)) s.Status = dto.Status;
            if (!string.IsNullOrEmpty(dto.Feedback)) s.Feedback = dto.Feedback;

            await _db.SaveChangesAsync();
            // Real-time updates via SSE removed; UI polls for updates.

            return Ok(s);
        }

        // SSE endpoint removed; clients should poll `/api/quiz/{id}` instead.
    }
}
