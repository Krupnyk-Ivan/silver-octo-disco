import os
import json
import logging
import asyncio
import re
import time
import random

import aio_pika
import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-review")

RABBIT_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBIT_USER = os.getenv("RABBITMQ_USER", "guest")
RABBIT_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
EXCHANGE = "med_events"
ROUTING_KEY = "submission.created"
QUEUE_NAME = "ai_review_queue"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://api-gateway")

# Set when the configured Ollama model is available via /api/models
MODEL_READY = False
LAST_MODEL_CHECK: float | None = None

app = FastAPI(title="AIReviewService")


@app.get("/")
async def root():
    return {"status": "ai-review running"}


def keyword_score(answer_text: str) -> int:
    text = (answer_text or "").lower()
    if "tourniquet" in text or "pressure" in text:
        return 100
    return 0


async def ask_llama(question: str, answer: str) -> tuple[int, str]:
    """Call Ollama /api/generate to ask Llama to score the answer and produce short feedback.

    Returns (score:int, feedback:str).
    The prompt asks for JSON: {"score": <int>, "feedback": "short text"} but we tolerate other formats.
    """
    if not MODEL_READY:
        raise RuntimeError("Ollama model not ready")
    prompt = (
        "You are a medical instructor. Evaluate the student's answer to the question below and return a JSON object"
        " with two keys: \"score\" (an integer 0-100) and \"feedback\" (a short helpful sentence)."
        " Output must be valid JSON only, for example: {\"score\": 85, \"feedback\": \"Good use of direct pressure...\"}."
        f"\n\nQuestion: {question}\n\nStudent Answer: {answer}\n\n"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "max_tokens": 150,
        "temperature": 0.0
    }
    url = f"{OLLAMA_URL.rstrip('/')}/api/generate"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Try to extract a textual output from common places
    text = ""
    if isinstance(data, dict):
        for key in ("output", "generated_text", "text", "result", "message"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                text = val
                break
        if not text:
            results = data.get("results") or data.get("choices")
            if isinstance(results, list) and results:
                first = results[0]
                if isinstance(first, dict):
                    for k in ("content", "text", "message", "output"):
                        v = first.get(k)
                        if isinstance(v, str) and v.strip():
                            text = v
                            break
                        if isinstance(v, dict):
                            t2 = v.get("text") or v.get("content")
                            if isinstance(t2, str) and t2.strip():
                                text = t2
                                break
    if not text:
        # fallback to full JSON string
        text = json.dumps(data)

    # Try to parse JSON from text
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            score = int(parsed.get("score") or parsed.get("Score") or 0)
            feedback = str(parsed.get("feedback") or parsed.get("Feedback") or "")
            score = max(0, min(100, score))
            return score, feedback
    except Exception:
        pass

    # Fallback: extract first integer and use remainder as feedback
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", text)
    score = None
    if m:
        try:
            val = int(m.group(1))
            score = max(0, min(100, val))
        except Exception:
            score = None

    feedback = text.strip()
    if score is None:
        raise ValueError("No integer score found in Ollama response")
    return score, feedback


async def process_message(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            payload = json.loads(message.body.decode())
        except Exception as e:
            logger.error("Invalid JSON message: %s", e)
            return

        answer_text = payload.get("AnswerText") or payload.get("answerText") or payload.get("Answer") or ""
        submission_id = payload.get("Id") or payload.get("id")
        student_id = payload.get("StudentId") or payload.get("studentId")
        question = payload.get("Question") or payload.get("question") or ""

        try:
            score, feedback = await ask_llama(question, answer_text)
        except Exception as e:
            logger.warning("Ollama scoring failed, falling back to keyword scoring: %s", e)
            score = keyword_score(answer_text)
            feedback = "Keywords matched" if score > 0 else "No keywords matched"

        logger.info("AI Review - SubmissionId=%s StudentId=%s Score=%s AnswerText=%s", submission_id, student_id, score, answer_text)

        # Post review via API Gateway so UI can fetch it
        if submission_id:
            try:
                review_url = f"{GATEWAY_URL.rstrip('/')}/tactical/quiz/{submission_id}/review"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(review_url, json={"Score": score, "Status": "Reviewed", "Feedback": feedback})
                    if r.status_code >= 300:
                        logger.warning("Failed to push review via gateway (status=%s): %s", r.status_code, r.text)
            except Exception as e:
                logger.warning("Error while pushing review via gateway: %s", e)


async def start_consumer():
    # Retry loop connecting to RabbitMQ with exponential backoff
    attempt = 0
    while True:
        try:
            amqp_url = f"amqp://{RABBIT_USER}:{RABBIT_PASSWORD}@{RABBIT_HOST}/"
            connection = await aio_pika.connect_robust(amqp_url)
            channel = await connection.channel()

            await channel.set_qos(prefetch_count=1)

            exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
            queue = await channel.declare_queue(QUEUE_NAME, durable=True)
            await queue.bind(exchange, routing_key=ROUTING_KEY)

            logger.info("Connected to RabbitMQ (async), waiting for messages...")
            await queue.consume(process_message)

            # keep the consumer task running; aio-pika's RobustConnection will handle reconnects
            # we use an indefinite wait so this coroutine stays alive while the connection is up
            await asyncio.Event().wait()
        except Exception as ex:
            attempt += 1
            wait = min(30, (2 ** attempt))
            logger.warning("RabbitMQ connection failed (attempt=%d). Retrying in %ds. Error: %s", attempt, wait, ex)
            await asyncio.sleep(wait)
        else:
            break


@app.on_event("startup")
async def startup_event():
    # Wait for Ollama readiness before starting the consumer (best-effort).
    async def wait_for_ollama(timeout_seconds: int = 60):
        attempts = 0
        wait = 1
        url_base = OLLAMA_URL.rstrip('/')
        endpoints = ["/api/ping", "/api/models", "/api/status", "/"]
        while attempts * wait < timeout_seconds:
            for ep in endpoints:
                try:
                    full = f"{url_base}{ep}"
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        r = await client.get(full)
                        # Treat only HTTP 200 as a positive readiness signal here.
                        if r.status_code == 200:
                            logging.info("Ollama responded OK at %s (status=%s)", full, r.status_code)
                            return True
                        else:
                            logging.debug("Ollama endpoint %s responded %s", full, r.status_code)
                except Exception:
                    pass
            attempts += 1
            await asyncio.sleep(wait)
            wait = min(10, wait * 2)
        return False

    try:
        ok = await wait_for_ollama(timeout_seconds=60)
        if not ok:
            logging.warning("Ollama did not become ready within timeout; continuing and will fallback if needed.")
    except Exception as e:
        logging.warning("Error while waiting for Ollama readiness: %s", e)
    # Start a background watcher that polls /api/models until the configured model appears
    async def model_watcher():
        global MODEL_READY, LAST_MODEL_CHECK
        url = f"{OLLAMA_URL.rstrip('/')}/api/models"
        attempt = 0
        # Exponential backoff with jitter to avoid tight polling while large model downloads occur
        while True:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(url)
                    LAST_MODEL_CHECK = time.time()
                    status = r.status_code
                    if status == 200:
                        try:
                            data = r.json()
                        except Exception:
                            data = None
                        names = []
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, str):
                                    names.append(item)
                                elif isinstance(item, dict) and item.get("name"):
                                    names.append(item.get("name"))
                        elif isinstance(data, dict):
                            for k in ("models", "results", "items"):
                                lst = data.get(k)
                                if isinstance(lst, list):
                                    for it in lst:
                                        if isinstance(it, str):
                                            names.append(it)
                                        elif isinstance(it, dict) and it.get("name"):
                                            names.append(it.get("name"))
                        if OLLAMA_MODEL in names:
                            MODEL_READY = True
                            logging.info("Ollama model %s is now available.", OLLAMA_MODEL)
                            break
                        else:
                            logging.info("Ollama /api/models returned 200 but model %s not listed yet.", OLLAMA_MODEL)
                    else:
                        # 404 is expected while model is pulling/extracting; log debug to avoid noise
                        if status == 404:
                            logging.debug("Ollama /api/models returned 404 (model may be downloading)")
                        else:
                            logging.info("Ollama /api/models returned status %s", status)
            except Exception as exc:
                logging.info("Error querying Ollama /api/models: %s", exc)

            attempt += 1
            # backoff: base 5s, double each attempt up to 60s, add random jitter +/-20%
            base = min(60, 5 * (2 ** (attempt - 1)))
            jitter = base * 0.2
            wait = max(5, base + random.uniform(-jitter, jitter))
            logging.info("Model %s not yet available, retrying in %.1fs...", OLLAMA_MODEL, wait)
            await asyncio.sleep(wait)

    @app.get('/health')
    async def health():
        return {
            'model_ready': MODEL_READY,
            'last_model_check': LAST_MODEL_CHECK,
        }

    asyncio.create_task(model_watcher())

    # Start the async consumer in background
    asyncio.create_task(start_consumer())
