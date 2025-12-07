using Microsoft.EntityFrameworkCore;
using QuizService.Models;

namespace QuizService.Data
{
    public class QuizDbContext : DbContext
    {
        public QuizDbContext(DbContextOptions<QuizDbContext> options) : base(options) { }

        public DbSet<QuizSubmission> QuizSubmissions { get; set; } = default!;
        public DbSet<Question> Questions { get; set; } = default!;
        public DbSet<KnowledgeItem> KnowledgeItems { get; set; } = default!;
        public DbSet<QuizAttempt> QuizAttempts { get; set; } = default!;
    }
}
