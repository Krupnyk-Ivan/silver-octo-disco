using Microsoft.EntityFrameworkCore;
using QuizService.Models;

namespace QuizService.Data
{
    public class QuizDbContext : DbContext
    {
        public QuizDbContext(DbContextOptions<QuizDbContext> options) : base(options) { }

        public DbSet<QuizSubmission> QuizSubmissions { get; set; } = default!;
    }
}
