using Microsoft.AspNetCore.Mvc;
using QuizService.Data;
using QuizService.Models;
using Microsoft.EntityFrameworkCore;

namespace QuizService.Controllers
{
    [ApiController]
    [Route("api/knowledge")]
    public class KnowledgeController : ControllerBase
    {
        private readonly QuizDbContext _db;

        public KnowledgeController(QuizDbContext db)
        {
            _db = db;
        }

        [HttpGet]
        public async Task<IActionResult> List()
        {
            var list = await _db.KnowledgeItems.OrderByDescending(k => k.CreatedAt).ToListAsync();
            return Ok(list);
        }

        [HttpGet("{id:guid}")]
        public async Task<IActionResult> Get(Guid id)
        {
            var item = await _db.KnowledgeItems.FirstOrDefaultAsync(x => x.Id == id);
            if (item == null) return NotFound();
            return Ok(item);
        }

        public class CreateDto
        {
            public string Title { get; set; } = string.Empty;
            public string Content { get; set; } = string.Empty;
            public string? Source { get; set; }
            public string? Tags { get; set; }
        }

        [HttpPost]
        public async Task<IActionResult> Create([FromBody] CreateDto dto)
        {
            var item = new KnowledgeItem
            {
                Id = Guid.NewGuid(),
                Title = dto.Title,
                Content = dto.Content,
                Source = dto.Source,
                Tags = dto.Tags
            };
            _db.KnowledgeItems.Add(item);
            await _db.SaveChangesAsync();
            return CreatedAtAction(nameof(Get), new { id = item.Id }, item);
        }
    }
}
