import os
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import httpx

app = FastAPI()
templates = Jinja2Templates(directory="templates")

GATEWAY = os.getenv("GATEWAY_URL", "http://api-gateway")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "gateway": GATEWAY})


@app.post("/submit")
async def submit(studentId: str = Form(...), question: str = Form(...), answerText: str = Form(...)):
    # Keep the original form POST behavior for non-JS fallback
    payload = {
        "StudentId": studentId,
        "Question": question,
        "AnswerText": answerText
    }
    async with httpx.AsyncClient() as client:
        url = f"{GATEWAY}/tactical/quiz/submit"
        resp = await client.post(url, json=payload, timeout=10.0)
        data = resp.json() if resp.status_code < 300 else {"error": resp.text}
    return HTMLResponse(content=f"<pre>{data}</pre><p><a href=\"/\">Back</a></p>")


@app.post("/api/submit")
async def api_submit(body: dict):
    # JSON proxy endpoint for AJAX UI
    async with httpx.AsyncClient() as client:
        try:
            url = f"{GATEWAY}/tactical/quiz/submit"
            resp = await client.post(url, json=body, timeout=10.0)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    return JSONResponse(status_code=resp.status_code, content=data)


@app.get("/api/get/{submission_id}")
async def api_get(submission_id: str):
    async with httpx.AsyncClient() as client:
        url = f"{GATEWAY}/tactical/quiz/{submission_id}"
        resp = await client.get(url, timeout=10.0)
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    return JSONResponse(status_code=resp.status_code, content=data)


@app.get("/api/quiz/events/{submission_id}")
async def proxy_events(submission_id: str):
    # Proxy SSE from the API gateway (which forwards to quiz-service) to the browser.
    url = f"{GATEWAY}/api/quiz/events/{submission_id}"
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            # Use stream to forward chunks as they arrive
            async with client.stream("GET", url) as resp:
                async def event_generator():
                    try:
                        async for chunk in resp.aiter_bytes():
                            # If upstream closed the stream, aiter_bytes will raise StreamClosed
                            yield chunk
                    except httpx.StreamClosed:
                        # Upstream closed the stream (e.g. gateway timeout). End cleanly.
                        return
                    except httpx.ReadError:
                        return
                    except Exception:
                        # On unexpected errors, stop the generator quietly so FastAPI can finish the response
                        return

                # Mirror the upstream content-type if provided, otherwise use text/event-stream
                content_type = resp.headers.get('content-type', 'text/event-stream')
                return StreamingResponse(event_generator(), media_type=content_type)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
