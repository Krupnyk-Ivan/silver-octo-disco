using Microsoft.AspNetCore.Mvc;
using QuizService.Data;
using QuizService.Models;
using QuizService.Services;
using Microsoft.EntityFrameworkCore;

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

            return CreatedAtAction(nameof(Get), new { id = submission.Id }, submission);
        }

        [HttpGet("{id:guid}")]
        public async Task<IActionResult> Get(Guid id)
        {
            var s = await _db.QuizSubmissions.FirstOrDefaultAsync(x => x.Id == id);
            if (s == null) return NotFound();
            return Ok(s);
        }
    }
}
