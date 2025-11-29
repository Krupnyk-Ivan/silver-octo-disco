import os
import json
import logging
import threading
import time

import pika
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-review")

RABBIT_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBIT_USER = os.getenv("RABBITMQ_USER", "guest")
RABBIT_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
EXCHANGE = "med_events"
ROUTING_KEY = "submission.created"
QUEUE_NAME = "ai_review_queue"

app = FastAPI(title="AIReviewService")


@app.get("/")
async def root():
    return {"status": "ai-review running"}


def analyze_answer(answer_text: str) -> int:
    text = (answer_text or "").lower()
    if "tourniquet" in text or "pressure" in text:
        return 100
    return 0


def on_message(ch, method, properties, body):
    try:
        payload = json.loads(body)
    except Exception as e:
        logger.error("Invalid JSON message: %s", e)
        ch.basic_ack(delivery_tag=method.delivery_tag)
        return

    answer_text = payload.get("AnswerText") or payload.get("answerText") or payload.get("Answer") or ""
    submission_id = payload.get("Id") or payload.get("id")
    student_id = payload.get("StudentId") or payload.get("studentId")

    score = analyze_answer(answer_text)

    # Simulate database update by logging
    logger.info("AI Review - SubmissionId=%s StudentId=%s Score=%s AnswerText=%s", submission_id, student_id, score, answer_text)

    ch.basic_ack(delivery_tag=method.delivery_tag)


def start_consumer():
    attempt = 0
    while True:
        try:
            credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASSWORD)
            params = pika.ConnectionParameters(host=RABBIT_HOST, credentials=credentials, heartbeat=60)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()

            channel.exchange_declare(exchange=EXCHANGE, exchange_type='topic', durable=True)
            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE, routing_key=ROUTING_KEY)

            logger.info("Connected to RabbitMQ, waiting for messages...")
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)
            channel.start_consuming()
        except Exception as ex:
            attempt += 1
            wait = min(30, (2 ** attempt))
            logger.warning("RabbitMQ connection failed (attempt=%d). Retrying in %ds. Error: %s", attempt, wait, ex)
            time.sleep(wait)
        else:
            break


@app.on_event("startup")
def startup_event():
    t = threading.Thread(target=start_consumer, daemon=True)
    t.start()
