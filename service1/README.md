# TacticalMed - Minimal Containerized Microservices Example

Services:

- `quiz-service` (C# .NET 8) - accepts quiz submissions, stores in EF InMemory and publishes to RabbitMQ.
- `ai-service` (Python FastAPI) - listens to RabbitMQ events, performs mock AI scoring.
- `api-gateway` (Ocelot) - routes client requests to quiz-service.
- `rabbitmq` - message broker (management UI on 15672).

Run (requires Docker & Docker Compose):

From repository root:

```powershell
docker compose up --build
```

Access:

- RabbitMQ management: http://localhost:15672 (guest/guest)
- API Gateway (exposed): http://localhost:7000
  - POST `/tactical/quiz/submit`
  - GET `/tactical/quiz/{id}`
- Quiz service (direct): http://localhost:5001/api/quiz

- Web UI (student): http://localhost:5500 (simple Python FastAPI UI)

Example POST:

```powershell
curl -X POST http://localhost:7000/tactical/quiz/submit -H "Content-Type: application/json" -d '{
  "StudentId":"student1",
  "Question":"What is the first step for massive hemorrhage?",
  "AnswerText":"Apply a tourniquet and direct pressure"
}'
```

Then check ai-service logs to see scoring output (score 100 for keywords "tourniquet" or "pressure").

Notes:

- The Python consumer retries connection if RabbitMQ isn't ready.
- The C# producer declares the topic exchange `med_events` and publishes to routing key `submission.created`.
