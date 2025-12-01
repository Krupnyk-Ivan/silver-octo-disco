using System;
using Microsoft.EntityFrameworkCore;
using QuizService.Data;
using QuizService.Services;
using OpenTelemetry.Trace;
using OpenTelemetry.Resources;

var builder = WebApplication.CreateBuilder(args);

builder.Configuration.AddEnvironmentVariables();

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

// Configure Postgres connection (fallback to a sensible default for docker-compose)
var defaultConn = "Host=postgres;Database=quizdb;Username=postgres;Password=postgres";
var conn = builder.Configuration.GetConnectionString("DefaultConnection") ?? Environment.GetEnvironmentVariable("ConnectionStrings__DefaultConnection") ?? defaultConn;

builder.Services.AddDbContext<QuizDbContext>(options =>
{
    options.UseNpgsql(conn);
});

builder.Services.AddSingleton<RabbitMqProducer>();

// OpenTelemetry tracing (OTLP exporter)
var otelEndpoint = Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT") ?? "http://jaeger:4317";
try
{
    builder.Services.AddOpenTelemetry()
        .WithTracing(tracerProviderBuilder =>
        {
            tracerProviderBuilder
                .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService("quiz-service"));
            try
            {
                tracerProviderBuilder.AddAspNetCoreInstrumentation();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Skipping AspNetCore instrumentation: {ex.Message}");
            }
            try
            {
                tracerProviderBuilder.AddHttpClientInstrumentation();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Skipping HttpClient instrumentation: {ex.Message}");
            }
            try
            {
                tracerProviderBuilder.AddEntityFrameworkCoreInstrumentation();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Skipping EF Core instrumentation: {ex.Message}");
            }
            try
            {
                tracerProviderBuilder.AddOtlpExporter(opts =>
                {
                    opts.Endpoint = new Uri(otelEndpoint);
                });
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Skipping OTLP exporter setup: {ex.Message}");
            }
        });
}
catch (Exception ex)
{
    Console.WriteLine($"OpenTelemetry init failed: {ex.Message}");
}

var app = builder.Build();

// Ensure DB created on startup
using (var scope = app.Services.CreateScope())
{
    var db = scope.ServiceProvider.GetRequiredService<QuizDbContext>();
    db.Database.EnsureCreated();
}

app.UseSwagger();
app.UseSwaggerUI();

app.MapControllers();

app.Run();
