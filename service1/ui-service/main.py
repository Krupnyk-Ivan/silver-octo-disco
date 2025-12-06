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


@app.get("/api/list")
async def api_list():
    # Proxy endpoint: GET list of submissions from the API gateway
    async with httpx.AsyncClient() as client:
        try:
            url = f"{GATEWAY}/tactical/quiz"
            resp = await client.get(url, timeout=10.0)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
    try:
        data = resp.json()
    except Exception:
        data = {"status_code": resp.status_code, "text": resp.text}
    return JSONResponse(status_code=resp.status_code, content=data)


# SSE proxy removed; UI uses polling-only endpoints (/api/get and /api/list)
