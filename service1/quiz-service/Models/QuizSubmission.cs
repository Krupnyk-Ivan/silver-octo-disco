using System.ComponentModel.DataAnnotations;

namespace QuizService.Models
{
    public class QuizSubmission
    {
        [Key]
        public Guid Id { get; set; }
        public string StudentId { get; set; } = default!;
        public string Question { get; set; } = default!;
        public string AnswerText { get; set; } = default!;
        public string Status { get; set; } = "Pending";
    }
}
