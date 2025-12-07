using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace QuizService.Models
{
    [System.ComponentModel.DataAnnotations.Schema.Table("knowledgeitems")]
    public class KnowledgeItem
    {
        [Key]
        [Column("id")]
        public Guid Id { get; set; }

        // Short descriptive title
        [Column("title")]
        public string Title { get; set; } = default!;

        // Main content the AI can use as context
        [Column("content")]
        public string Content { get; set; } = default!;

        // Optional source or reference URL
        [Column("source")]
        public string? Source { get; set; }

        // Optional tags to help searching/filtering (comma-separated)
        [Column("tags")]
        public string? Tags { get; set; }

        [Column("created_at")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
