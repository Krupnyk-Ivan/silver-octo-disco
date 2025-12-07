using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace QuizService.Models
{
    [System.ComponentModel.DataAnnotations.Schema.Table("questions")]
    public class Question
    {
        [Key]
        [Column("id")]
        public Guid Id { get; set; }

        // Short title for lists
        [Column("title")]
        public string Title { get; set; } = default!;

        // Full question text
        [Column("text")]
        public string Text { get; set; } = default!;

        // Optional JSON-encoded choices (e.g. ["A","B","C"]) or null for free-text
        [Column("choices")]
        public string? ChoicesJson { get; set; }

        // Optional correct answer (for automated grading or display)
        [Column("correct_answer")]
        public string? CorrectAnswer { get; set; }

        // When the question was added
        [Column("created_at")]
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
