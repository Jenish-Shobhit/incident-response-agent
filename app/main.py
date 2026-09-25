"""The HTTP layer: serve the page, stream a run, take an approval.

**There are two streams, not one, and that is forced by the design rather than chosen.**
``interrupt()`` ends the run -- the generator behind ``/run`` returns, and the connection
closes. Approval arrives later on a separate request, and resuming produces a second,
shorter stream. Trying to hold one connection open across a human decision means holding
a socket open for however long the person takes, and there is nothing to send them
meanwhile.

The thread id is what joins the two. It is minted in ``/run``, sent to the browser in the
first frame, and handed back with the approval so LangGraph can find the checkpoint.
"""

import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

from app.evidence import normalise
from app.graph import app_graph, run_config
from app.llm import describe, reset_mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB = Path(os.environ.get("WEB_DIR", PROJECT_ROOT / "web"))
INCIDENT = Path(os.environ.get("INCIDENT", PROJECT_ROOT / "data" / "incident.json"))

app = FastAPI(title="Agentic Incident Response")

# `?demo` fetches web/demo/frames.json, and it is the one path that has to work when
# nothing else does -- no model, no credentials, no network. Without this mount the
# offline demo 404s, which is the exact moment it was supposed to save you.
if (WEB / "demo").is_dir():
    app.mount("/demo", StaticFiles(directory=WEB / "demo"), name="demo")


def sse(frame):
    """One SSE frame. Always a `data:` line, always JSON, always carrying a key `e`.

    Named events would need a matching addEventListener per type in the browser; one
    switch on `e` costs about thirty fewer lines and reads the same on the wire.
    """
    return "data: " + json.dumps(frame, default=str) + "\n\n"


@app.get("/")
def index():
    path = WEB / "index.html"
    if not path.exists():
        raise HTTPException(500, f"{path} is missing")
    return FileResponse(path)


@app.get("/health")
def health():
    return {"ok": True, "model": describe(), "mock": os.environ.get("MOCK", "1")}


@app.get("/incident")
def incident():
    """The raw incident, for the audit view. This is the only place raw log text is served."""
    with open(INCIDENT) as f:
        return json.load(f)


@app.post("/load")
async def load(request: Request):
    """Normalise an uploaded incident file and hand back the incident.

    This is the same function the CLI normaliser calls, so an uploaded file is treated
    exactly like the one on disk, and the browser never has to know the input's shape.
    """
    try:
        source = await request.json()
    except Exception:
        raise HTTPException(400, "that file is not valid JSON")
    if not isinstance(source, dict) or "logs" not in source:
        raise HTTPException(400, "expected an incident with a logs array")
    try:
        incident = normalise(source)
    except (KeyError, TypeError) as exc:
        raise HTTPException(400, f"unexpected shape: {exc}")
    if not incident["evidence"]:
        raise HTTPException(400, "that file contains no evidence records")
    return incident


@app.post("/run")
async def run(request: Request):
    """Start a run. The stream ends when the graph stops at the approval gate."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    if body.get("incident"):
        inc = body["incident"]
    else:
        if not INCIDENT.exists():
            raise HTTPException(400, f"{INCIDENT} missing -- run python tools/normalise.py first")
        with open(INCIDENT) as f:
            inc = json.load(f)

    thread_id = str(uuid.uuid4())
    cfg = run_config(thread_id)
    reset_mock()

    def stream():
        yield sse({"e": "start", "thread_id": thread_id, "model": describe()})
        try:
            for mode, chunk in app_graph.stream(
                {"incident": inc}, cfg, stream_mode=["custom", "updates"]
            ):
                if mode == "custom":
                    yield sse(chunk)
                else:
                    for node in chunk:
                        if node != "__interrupt__":
                            yield sse({"e": "node", "node": node})

            state = app_graph.get_state(cfg)
            tokens = {
                "in": state.values.get("tokens_in", 0),
                "out": state.values.get("tokens_out", 0),
            }
            yield sse({"e": "tokens", **tokens})
            yield sse({"e": "done", "thread_id": thread_id, "awaiting": bool(state.next)})
        except Exception as exc:  # a failed run must still close the stream cleanly
            yield sse({"e": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/approve")
async def approve(request: Request):
    """Resume a stopped run with the human's decision. A second, shorter stream."""
    body = await request.json()
    thread_id = body.get("thread_id")
    approved = body.get("approved_ids", [])
    if not thread_id:
        raise HTTPException(400, "thread_id is required")

    cfg = run_config(thread_id)
    state = app_graph.get_state(cfg)
    if not state.next:
        raise HTTPException(409, "this run is not waiting for an approval")

    def stream():
        try:
            for mode, chunk in app_graph.stream(
                Command(resume={"approved_ids": approved}), cfg, stream_mode=["custom", "updates"]
            ):
                if mode == "custom":
                    yield sse(chunk)
                else:
                    for node in chunk:
                        if node != "__interrupt__":
                            yield sse({"e": "node", "node": node})

            final = app_graph.get_state(cfg)
            yield sse(
                {
                    "e": "receipt",
                    "receipts": final.values.get("receipts", []),
                    "approved_ids": final.values.get("approved_ids", []),
                    "skipped": [
                        r["id"]
                        for r in final.values.get("plan", [])
                        if r["id"] not in set(final.values.get("approved_ids", []))
                    ],
                }
            )
            yield sse({"e": "done", "thread_id": thread_id, "awaiting": False})
        except Exception as exc:
            yield sse({"e": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
