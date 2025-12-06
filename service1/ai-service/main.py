import os
import json
import logging
import asyncio
import re
import time
import aio_pika
import httpx
from fastapi import FastAPI

# --- logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("ai_service.log", mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ai-review")

# runtime configuration
RABBIT_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBIT_USER = os.getenv("RABBITMQ_USER", "guest")
RABBIT_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
EXCHANGE = "med_events"
ROUTING_KEY = "submission.created"
QUEUE_NAME = "ai_review_queue"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://api-gateway")

MODEL_READY = False
LAST_MODEL_CHECK: float | None = None

# --- OpenTelemetry init (optional, safe if libs missing) ---
try:
    from opentelemetry import trace, propagate
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    _otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")
    _service_name = os.getenv("OTEL_SERVICE_NAME", "ai-service")

    resource = Resource.create({"service.name": _service_name})
    provider = TracerProvider(resource=resource)
    otlp_exporter = OTLPSpanExporter(endpoint=_otel_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
    trace.set_tracer_provider(provider)

    # Instrumentations (FastAPI app object will be instrumented on startup)
    HTTPXClientInstrumentor().instrument()
    _otel_enabled = True
except Exception as _e:
    _otel_enabled = False
    # safe fallback: continue without telemetry
    logger.info(f"OpenTelemetry not initialized: {_e}")
# ---------------------------------------------------------

app = FastAPI(title="AIReviewService")

@app.get("/")
async def root():
    return {"status": "ai-review running", "model_ready": MODEL_READY}

def keyword_score(answer_text: str) -> int:
    text = (answer_text or "").lower()
    if "tourniquet" in text or "pressure" in text:
        return 100
    return 0

async def ask_llama(question: str, answer: str) -> tuple[int, str]:
    """Відправляє запит до Ollama і намагається розпарсити результат."""
    if not MODEL_READY:
        raise RuntimeError("Ollama model not ready")
    
    prompt = (
        "You are a medical instructor. Evaluate the student's answer to the question below and return a JSON object"
        " with two keys: \"score\" (an integer 0-100) and \"feedback\" (a short helpful sentence)."
        " Output must be valid JSON only."
        f"\n\nQuestion: {question}\n\nStudent Answer: {answer}\n\n"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0}
    }
    url = f"{OLLAMA_URL.rstrip('/')}/api/generate"
    
    # Таймаут 300 сек для надійності
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        # Read raw text first — avoid raising on JSONDecodeError from multiple JSON objects
        text_body = resp.text

    # Спроба розпарсити тіло як JSON; не піднімаємо помилку тут, будемо працювати з текстом у будь-якому випадку
    data = None
    try:
        data = json.loads(text_body)
    except Exception:
        data = None

    # Витягнути текст відповіді з полів JSON, якщо вони є, інакше використовуємо сирий body
    text = ""
    if isinstance(data, dict):
        text = data.get("response") or data.get("output") or data.get("text") or ""
    if not text:
        text = text_body or ""

    # ЛОГУВАННЯ СИРОЇ ВІДПОВІДІ (тепер піде і в файл)
    logger.info(f"Ollama raw response: {text}")

    # Спроба розпарсити JSON з тексту
    try:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as e:
                # Обробка помилки "Extra data" (якщо Llama дописала щось після JSON)
                if e.msg.startswith("Extra data"):
                    logger.warning(f"JSON extra data detected, trimming at {e.pos}")
                    parsed = json.loads(json_str[:e.pos])
                else:
                    raise e
            
            score = int(parsed.get("score", 0))
            feedback = str(parsed.get("feedback", "No feedback provided."))
            score = max(0, min(100, score))
            return score, feedback
    except Exception as e:
        logger.warning(f"JSON parsing failed: {e}. Falling back to regex.")

    # Fallback: шукаємо число
    numbers = re.findall(r'\d+', text)
    if numbers:
        score = int(numbers[0])
        score = max(0, min(100, score))
        return score, text.strip()
    
    return 0, text.strip()

async def process_message(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            payload = json.loads(message.body.decode())
        except Exception as e:
            logger.error("Invalid JSON message: %s", e)
            return

        answer_text = payload.get("AnswerText") or payload.get("answerText") or ""
        submission_id = payload.get("Id") or payload.get("id")
        question = payload.get("Question") or payload.get("question") or ""

        # Extract trace context from message headers (if present)
        try:
            if _otel_enabled:
                tracer = trace.get_tracer(__name__)
                headers = {}
                try:
                    headers = dict(message.headers or {})
                except Exception:
                    headers = {}

                def _getter(carrier, key):
                    return carrier.get(key)

                ctx = propagate.extract(_getter, headers)
                with tracer.start_as_current_span("ai.process_message", context=ctx) as span:
                    span.set_attribute("messaging.system", "rabbitmq")
                    span.set_attribute("messaging.destination", EXCHANGE)
                    span.set_attribute("messaging.rabbitmq.routing_key", ROUTING_KEY)
                    span.set_attribute("messaging.message_id", str(submission_id))
                    logger.info(f"Received submission {submission_id}. Asking AI...")

                    try:
                        score, feedback = await ask_llama(question, answer_text)
                    except Exception as e:
                        logger.warning(f"Ollama failed, using keywords. Error: {e}")
                        score = keyword_score(answer_text)
                        feedback = "AI unavailable, checked keywords."

                    logger.info(f"AI Result: Score={score} Feedback='{feedback}'")

                    if submission_id:
                        try:
                            review_url = f"{GATEWAY_URL.rstrip('/')}/tactical/quiz/{submission_id}/review"
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                await client.post(review_url, json={"Score": score, "Status": "Reviewed", "Feedback": feedback})
                        except Exception as e:
                            logger.warning(f"Failed to push review to Gateway: {e}")
                    return

        except Exception as ex:
            logger.debug(f"Telemetry/context extraction skipped or failed: {ex}")

        # Fallback path when OTEL not enabled or extraction failed
        logger.info(f"Received submission {submission_id}. Asking AI...")
        try:
            score, feedback = await ask_llama(question, answer_text)
        except Exception as e:
            logger.warning(f"Ollama failed, using keywords. Error: {e}")
            score = keyword_score(answer_text)
            feedback = "AI unavailable, checked keywords."

        logger.info(f"AI Result: Score={score} Feedback='{feedback}'")

        if submission_id:
            try:
                review_url = f"{GATEWAY_URL.rstrip('/')}/tactical/quiz/{submission_id}/review"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(review_url, json={"Score": score, "Status": "Reviewed", "Feedback": feedback})
            except Exception as e:
                logger.warning(f"Failed to push review to Gateway: {e}")

async def start_consumer():
    while True:
        try:
            amqp_url = f"amqp://{RABBIT_USER}:{RABBIT_PASSWORD}@{RABBIT_HOST}/"
            connection = await aio_pika.connect_robust(amqp_url)
            channel = await connection.channel()
            
            exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
            queue = await channel.declare_queue(QUEUE_NAME, durable=True)
            await queue.bind(exchange, routing_key=ROUTING_KEY)

            logger.info("Connected to RabbitMQ.")
            await channel.set_qos(prefetch_count=1)
            await queue.consume(process_message)
            await asyncio.Future()
        except Exception as ex:
            logger.warning(f"RabbitMQ connection retrying... {ex}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    async def model_watcher():
        global MODEL_READY
        url = f"{OLLAMA_URL.rstrip('/')}/api/tags"
        while True:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        models = [m.get('name') for m in data.get('models', [])]
                        if any(OLLAMA_MODEL in m for m in models):
                            MODEL_READY = True
                            logger.info(f"Model {OLLAMA_MODEL} detected and ready!")
                            break
                        else:
                            logger.info(f"Waiting for model {OLLAMA_MODEL}... Found: {models}")
            except Exception as e:
                logger.info(f"Ollama check failed: {e}")
            await asyncio.sleep(5)

    # If OpenTelemetry is available, instrument the FastAPI app now
    try:
        if _otel_enabled:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor().instrument_app(app)
    except Exception:
        logger.debug("FastAPI instrumentation skipped")

    asyncio.create_task(model_watcher())
    asyncio.create_task(start_consumer())