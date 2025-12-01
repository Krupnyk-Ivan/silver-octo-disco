using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Ocelot.DependencyInjection;
using Ocelot.Middleware;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

var builder = WebApplication.CreateBuilder(args);

// --- OpenTelemetry Configuration (Новий синтаксис) ---
builder.Services.AddOpenTelemetry()
	.WithTracing(tracerProviderBuilder =>
	{
		tracerProviderBuilder
				.SetResourceBuilder(ResourceBuilder.CreateDefault().AddService("api-gateway"));
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
				tracerProviderBuilder.AddOtlpExporter(opts =>
				{
					// Адреса Jaeger з docker-compose
					opts.Endpoint = new Uri(builder.Configuration["OTEL_EXPORTER_OTLP_ENDPOINT"] ?? "http://jaeger:4317");
				});
			}
			catch (Exception ex)
			{
				Console.WriteLine($"Skipping OTLP exporter setup: {ex.Message}");
			}
	});
// -----------------------------------------------------

builder.Configuration.AddJsonFile("ocelot.json", optional: false, reloadOnChange: true);
builder.Services.AddOcelot(builder.Configuration);

var app = builder.Build();

await app.UseOcelot();

app.Run();
