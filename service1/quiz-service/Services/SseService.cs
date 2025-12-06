using System.Collections.Concurrent;
using System.Threading.Channels;
using System.Linq;
using Microsoft.Extensions.Logging;

namespace QuizService.Services
{
    public class SseService
    {
        private readonly ConcurrentDictionary<string, List<Channel<string>>> _subs = new();
        private readonly ILogger<SseService> _logger;

        public SseService(ILogger<SseService> logger)
        {
            _logger = logger;
        }

        public ChannelReader<string> Subscribe(string id)
        {
            var ch = Channel.CreateUnbounded<string>();
            var list = _subs.GetOrAdd(id, _ => new List<Channel<string>>());
            lock (list)
            {
                list.Add(ch);
                _logger.LogInformation("SSE subscribe: {id} (subscribers={count})", id, list.Count);
            }
            return ch.Reader;
        }

        public void Unsubscribe(string id, ChannelReader<string> reader)
        {
            if (_subs.TryGetValue(id, out var list))
            {
                lock (list)
                {
                    var toRemove = list.FirstOrDefault(c => c.Reader == reader);
                    if (toRemove != null) list.Remove(toRemove);
                    if (list.Count == 0) _subs.TryRemove(id, out _);
                    _logger.LogInformation("SSE unsubscribe: {id} (remaining={count})", id, list.Count);
                }
            }
        }

        public async Task PublishAsync(string id, string message)
        {
            if (_subs.TryGetValue(id, out var list))
            {
                List<Channel<string>> snapshot;
                lock (list) { snapshot = list.ToList(); }
                _logger.LogInformation("Publishing SSE to {id} for {n} subscribers", id, snapshot.Count);
                var tasks = snapshot.Select(async ch =>
                {
                    try { await ch.Writer.WriteAsync(message); }
                    catch (Exception ex) { _logger.LogWarning(ex, "Failed to write SSE message for {id}", id); }
                });
                await Task.WhenAll(tasks);
            }
            else
            {
                _logger.LogInformation("No SSE subscribers for {id}", id);
            }
        }
    }
}
