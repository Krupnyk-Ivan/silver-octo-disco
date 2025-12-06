## Repository overview

This repo is a minimal, containerized microservices example for a tactical-med quiz flow. Key services:

- `quiz-service` (C# .NET 8): stores submissions, publishes events to RabbitMQ via the RabbitMQ Management HTTP API.
- `ai-service` (Python FastAPI): consumes RabbitMQ messages (aio-pika), asks Ollama for scoring, falls back to keyword scoring.
- `api-gateway` (Ocelot): routes public paths under `/tactical/quiz/*` to `quiz-service`.
  -- `ui-service` (FastAPI + Jinja): simple web UI; polls the gateway for submission state (`/api/list`, `/api/get/{id}`).
- `rabbitmq`, `postgres`, `ollama`, `jaeger` are provided by `docker-compose.yml`.

## Quick start (what humans run)

- From repository root: `docker compose up --build` (exposes gateway on `:7000`, UI on `:5500`, RabbitMQ management on `:15672`).

## Important files to inspect (use these as primary anchors)

- `docker-compose.yml` — service names, ports, and env defaults used by CI/local runs.
  -- `quiz-service/Controllers/QuizController.cs` — REST endpoints for submitting and retrieving quizzes; UI polls `/api/quiz` and `/api/quiz/{id}`.
- `quiz-service/Services/RabbitMqProducer.cs` — publishes events using RabbitMQ _management HTTP API_ (not RabbitMQ.Client). Any code changes that publish events must keep compatibility with this approach or change docker-compose accordingly.
- `ai-service/main.py` — RabbitMQ consumer using `aio-pika`, `ask_llama()` logic, keyword fallback, model readiness watcher (`/api/tags`), and calls gateway review endpoint to post results.
- `api-gateway/ocelot.json` — upstream → downstream route mapping (shows `UpstreamPathTemplate` and host/port targets used by gateway).
  -- `ui-service/main.py` and `ui-service/templates/index.html` — simple UI that polls the gateway for lists and submission details.

## Architecture and data flow (concise)

1. Client (UI or direct) POSTs to `api-gateway` → `/tactical/quiz/submit`.
2. `api-gateway` forwards to `quiz-service` `/api/quiz/submit` which: persists to Postgres, then publishes an event to exchange `med_events` with routing key `submission.created`.
3. `ai-service` consumes messages bound to `med_events` / `submission.created` (queue `ai_review_queue`), scores the answer (calls Ollama at `OLLAMA_URL`), and posts review back to `GATEWAY_URL/tactical/quiz/{id}/review`.
4. `quiz-service` receives review POST and updates DB. The UI polls the gateway for updates; SSE support removed.

Key message fields (observed): `Id`, `StudentId`, `Question`, `AnswerText`, `Status`.

## Project-specific conventions & pitfalls for agents

- Message publishing is done via HTTP management API (see `RabbitMqProducer.cs`). This means:
  - Tests or local stubs must mimic the management API semantics or provide a real RabbitMQ management endpoint on port `15672`.
  - Publishing uses `payload` string encoded JSON in the management POST; don't replace this with binary framing unless you also update consumer expectations.
- `ai-service` expects the Ollama model to be present and checks `/api/tags`; `docker-compose` runs an `ollama-init` helper that pulls the model. When modifying AI call behavior, keep the `MODEL_READY` watcher and the error fallback in mind.
  -- Real-time updates previously used SSE; the project now relies on client polling. When changing the submission payload, update `QuizController.Review`, `api-gateway/ocelot.json`, and `ui-service` polling endpoints (`/api/list`, `/api/get/{id}`).
- Telemetry (OpenTelemetry) is optional and guarded with try/except in both Python and C# code. Instrumentation may be present but is safe to skip in dev environments.
- Database: the code uses Npgsql/Postgres by default (`QuizDbContext` + connection string from `ConnectionStrings__DefaultConnection`). A README comment incorrectly mentions EF InMemory; rely on `quiz-service/Program.cs` for the truth.

## Build & run commands for automation

- Start all services locally: `docker compose up --build`.
- Rebuild a single service container: `docker compose build <service>` (e.g. `ai-service`).
- Inspect RabbitMQ UI: `http://localhost:15672` (guest/guest).

## When editing messaging or schema

- Update both sides (producer and consumer): `quiz-service/Controllers/QuizController.cs` (payload shape) and `ai-service/main.py` (consumer field lookup). Also update any test fixtures and `ui-service` handlers.
- Update `ocelot.json` routes if you rename upstream paths.

## Small, actionable examples for agents

- To find where events are published: open `quiz-service/Services/RabbitMqProducer.cs` and search for `publish` usage in `quiz-service/Controllers/QuizController.cs`.
- Message example sent by controller (stringified JSON):
  {
  "Id": "<guid>",
  "StudentId": "student1",
  "Question": "...",
  "AnswerText": "...",
  "Status": "Pending"
  }
- AI result postback example: `POST {GATEWAY_URL}/tactical/quiz/{id}/review` with JSON `{ "Score": 100, "Status": "Reviewed", "Feedback": "..." }`.

## Tests & missing coverage

- There are no test projects in the repo. Agents should avoid assuming test harnesses exist and should add focused tests when modifying logic (unit tests for `ask_llama()` parsing, and integration tests that mock RabbitMQ management API).

## Editing & PR guidance for AI agents

- Small, isolated changes are preferred. When changing cross-service contracts (message shape, route paths, or exchange/routing keys), include:
  - Code changes in both sides (producer + consumer).
  - Update to `docker-compose.yml` if new services/ports are required.
  - End-to-end manual validation steps (how to submit and where to view results).

---

If anything in these notes seems incomplete or you want examples added (e.g., test stubs, sample cURL runs), tell me which area to expand and I'll update this file.
