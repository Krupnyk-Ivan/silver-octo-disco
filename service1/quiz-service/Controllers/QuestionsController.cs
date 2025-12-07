using Microsoft.AspNetCore.Mvc;
using QuizService.Data;
using QuizService.Models;
using Microsoft.EntityFrameworkCore;

namespace QuizService.Controllers
{
    [ApiController]
    [Route("api/questions")]
    public class QuestionsController : ControllerBase
    {
        private readonly QuizDbContext _db;

        public QuestionsController(QuizDbContext db)
        {
            _db = db;
        }

        [HttpGet]
        public async Task<IActionResult> List()
        {
            var list = await _db.Questions.OrderByDescending(q => q.CreatedAt).ToListAsync();
            return Ok(list);
        }

        // GET /api/questions/random/{count}
        [HttpGet("random/{count:int}")]
        public async Task<IActionResult> Random(int count = 5)
        {
            if (count <= 0) count = 5;
            // Use database random ordering when possible
            try
            {
                var list = await _db.Questions
                    .OrderBy(q => EF.Functions.Random())
                    .Take(count)
                    .ToListAsync();
                return Ok(list);
            }
            catch
            {
                // Fallback: load all and pick random on server
                var all = await _db.Questions.ToListAsync();
                var rnd = new Random();
                var sample = all.OrderBy(x => rnd.Next()).Take(count).ToList();
                return Ok(sample);
            }
        }

        [HttpGet("{id:guid}")]
        public async Task<IActionResult> Get(Guid id)
        {
            var q = await _db.Questions.FirstOrDefaultAsync(x => x.Id == id);
            if (q == null) return NotFound();
            return Ok(q);
        }

        public class CreateDto
        {
            public string Title { get; set; } = string.Empty;
            public string Text { get; set; } = string.Empty;
            public string? ChoicesJson { get; set; }
            public string? CorrectAnswer { get; set; }
        }

        [HttpPost]
        public async Task<IActionResult> Create([FromBody] CreateDto dto)
        {
            var q = new Question
            {
                Id = Guid.NewGuid(),
                Title = dto.Title,
                Text = dto.Text,
                ChoicesJson = dto.ChoicesJson,
                CorrectAnswer = dto.CorrectAnswer
            };
            _db.Questions.Add(q);
            await _db.SaveChangesAsync();
            return CreatedAtAction(nameof(Get), new { id = q.Id }, q);
        }
    }
}
