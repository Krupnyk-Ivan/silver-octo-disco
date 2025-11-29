using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Configuration;

namespace QuizService.Services
{
    // Note: This implementation publishes events using the RabbitMQ Management HTTP API.
    // This avoids dependency/version issues with the RabbitMQ.Client binary in the build container,
    // while still delivering messages to the broker's exchange `med_events` with a routing key.
    public class RabbitMqProducer : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _managementUrl;

        public RabbitMqProducer(IConfiguration configuration)
        {
            var host = configuration["RABBITMQ_HOST"] ?? "rabbitmq";
            var user = configuration["RABBITMQ_USER"] ?? "guest";
            var pass = configuration["RABBITMQ_PASSWORD"] ?? "guest";

            _managementUrl = $"http://{host}:15672/api";

            _httpClient = new HttpClient();
            var auth = Convert.ToBase64String(Encoding.ASCII.GetBytes($"{user}:{pass}"));
            _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Basic", auth);
        }

        public void Publish(string exchange, string routingKey, string message)
        {
            var requestUrl = $"{_managementUrl}/exchanges/%2F/{Uri.EscapeDataString(exchange)}/publish";

            var payload = new
            {
                properties = new { },
                routing_key = routingKey,
                payload = message,
                payload_encoding = "string"
            };

            var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
            var resp = _httpClient.PostAsync(requestUrl, content).GetAwaiter().GetResult();
            if (!resp.IsSuccessStatusCode)
            {
                throw new Exception($"Failed to publish message via management API: {resp.StatusCode} - {resp.ReasonPhrase}");
            }
        }

        public void Dispose()
        {
            try { _httpClient?.Dispose(); } catch { }
        }
    }
}
