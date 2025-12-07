using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace QuizService.Models
{
    [System.ComponentModel.DataAnnotations.Schema.Table("quizsubmissions")]
    public class QuizSubmission
    {
        [Key]
        [Column("id")]
        public Guid Id { get; set; }

        [Column("studentid")]
        public string StudentId { get; set; } = default!;

        [Column("question")]
        public string Question { get; set; } = default!;

        [Column("answertext")]
        public string AnswerText { get; set; } = default!;

        [Column("status")]
        public string Status { get; set; } = "Pending";
        // Score set by AI review service (nullable until reviewed)
        [Column("score")]
        public int? Score { get; set; }
        // Optional textual feedback produced by AI reviewer
        [Column("feedback")]
        public string? Feedback { get; set; }

        // Link to question (if submission is for a known question)
        [Column("question_id")]
        public Guid? QuestionId { get; set; }

        // Link to grouped attempt
        [Column("attempt_id")]
        public Guid? AttemptId { get; set; }
    }
}
