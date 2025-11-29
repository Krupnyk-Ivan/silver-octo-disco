using Microsoft.EntityFrameworkCore;
using QuizService.Data;
using QuizService.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddEnvironmentVariables();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

builder.Services.AddDbContext<QuizDbContext>(options =>
{
    options.UseInMemoryDatabase("quizdb");
});

builder.Services.AddSingleton<RabbitMqProducer>();

var app = builder.Build();

app.UseSwagger();
app.UseSwaggerUI();

app.MapControllers();

app.Run();
