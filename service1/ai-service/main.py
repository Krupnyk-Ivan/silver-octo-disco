import os
import json
import logging
import asyncio
import re

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

            # keep running until connection drops
            await connection.wait_closed()
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
                        if r.status_code < 500:
                            logging.info("Ollama responded at %s (status=%s)", full, r.status_code)
                            return True
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

    # Start the async consumer in background
    asyncio.create_task(start_consumer())
