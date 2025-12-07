using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace QuizService.Models
{
    [Table("quizattempts")]
    public class QuizAttempt
    {
        [Key]
        [Column("id")]
        public Guid Id { get; set; }

        [Column("studentid")]
        public string StudentId { get; set; } = default!;

        [Column("started_at")]
        public DateTime StartedAt { get; set; } = DateTime.UtcNow;

        [Column("duration_minutes")]
        public int DurationMinutes { get; set; } = 5;

        [Column("completed_at")]
        public DateTime? CompletedAt { get; set; }

        [Column("score")]
        public int? Score { get; set; }

        [Column("feedback")]
        public string? Feedback { get; set; }

        // Optional: concatenated prompt / context used for AI
        [Column("prompt_used")]
        public string? PromptUsed { get; set; }
    }
}
