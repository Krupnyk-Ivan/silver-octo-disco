using System.Collections.Concurrent;
using System.Threading.Channels;
using System.Linq;

namespace QuizService.Services
{
    public class SseService
    {
        private readonly ConcurrentDictionary<string, List<Channel<string>>> _subs = new();

        public ChannelReader<string> Subscribe(string id)
        {
            var ch = Channel.CreateUnbounded<string>();
            var list = _subs.GetOrAdd(id, _ => new List<Channel<string>>());
            lock (list)
            {
                list.Add(ch);
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
                }
            }
        }

        public async Task PublishAsync(string id, string message)
        {
            if (_subs.TryGetValue(id, out var list))
            {
                List<Channel<string>> snapshot;
                lock (list) { snapshot = list.ToList(); }
                var tasks = snapshot.Select(async ch =>
                {
                    try { await ch.Writer.WriteAsync(message); }
                    catch { /* ignore */ }
                });
                await Task.WhenAll(tasks);
            }
        }
    }
}
