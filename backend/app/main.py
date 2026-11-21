import hashlib
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import litellm
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


MODEL = os.getenv("LLM_MODEL", "gemini/gemini-3-flash-preview")
logger = logging.getLogger("lyftr.backend")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////data/app.db")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
ENABLE_FAILURE_SIMULATION = os.getenv("ENABLE_FAILURE_SIMULATION", "false").lower() == "true"
LLM_KEYS = [
    key.strip()
    for key in os.getenv("LLM_API_KEYS", "").split(",")
    if key.strip()
]

litellm.caching = True
litellm.cache = litellm.Cache(type="local")


def database_path() -> str:
    return DATABASE_URL.removeprefix("sqlite:///")


def connect():
    connection = sqlite3.connect(database_path(), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database():
    path = database_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS messages_session_id_idx ON messages(session_id, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS response_cache (
                cache_key TEXT PRIMARY KEY,
                reply TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

initialize_database()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    message: str
    system_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: dict


def read_history(session_id: str):
    with connect() as connection:
        rows = connection.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def add_message(session_id: str, role: str, content: str, metadata=None):
    with connect() as connection:
        connection.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(metadata) if metadata is not None else None,
                iso_now(),
            ),
        )


def parse_simulation(header: Optional[str]):
    if not header:
        return {}
    result = {}
    for item in header.split(","):
        if "=" not in item:
            continue
        key_id, status = (part.strip() for part in item.split("=", 1))
        if status in {"429", "500", "502", "503"}:
            result[key_id] = int(status)
    return result


def cache_key(messages):
    payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{MODEL}:{payload}".encode("utf-8")).hexdigest()


def find_cached(key: str):
    with connect() as connection:
        row = connection.execute(
            "SELECT reply, model, input_tokens, output_tokens FROM response_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
    return dict(row) if row else None


def store_cached(key: str, reply: str, model: str, input_tokens: int, output_tokens: int):
    with connect() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO response_cache
            (cache_key, reply, model, input_tokens, output_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, reply, model, input_tokens, output_tokens, iso_now()),
        )


def token_count(response):
    usage = getattr(response, "usage", None)
    if usage is None:
        usage = getattr(response, "_hidden_params", {}).get("usage")
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def demo_reply(messages):
    question = messages[-1]["content"].lower()
    if "capital" in question and "france" in question:
        return "The capital of France is Paris."
    if "hello" in question or "hi " in question:
        return "Hello! How can I help you today?"
    return "I’m ready to help. Add a valid LLM_API_KEYS value to enable live model responses."


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health():
    try:
        with connect() as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok", "keys_configured": len(LLM_KEYS), "cache_enabled": True}


@app.post("/chat")
def chat(payload: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    session_id = payload.session_id.strip()
    message = payload.message.strip()
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    if not message:
        raise HTTPException(status_code=422, detail="message is required")
    if len(message) > 4000:
        raise HTTPException(status_code=422, detail="message must be 4000 characters or fewer")

    history = read_history(session_id)
    system_prompt = payload.system_prompt or "You are a helpful assistant."
    messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": message}]
    key = cache_key(messages)

    started = time.perf_counter()
    cached = find_cached(key)
    if cached:
        latency = max(1, int((time.perf_counter() - started) * 1000))
        metadata = {
            "resolution_source": "LLM_CACHE",
            "model": cached["model"],
            "latency_ms": latency,
            "input_tokens": cached["input_tokens"],
            "output_tokens": cached["output_tokens"],
            "key_id": None,
            "fallback_attempts": 0,
        }
        add_message(session_id, "user", message)
        add_message(session_id, "assistant", cached["reply"], metadata)
        return {"session_id": session_id, "reply": cached["reply"], "metadata": metadata}

    simulations = parse_simulation(x_simulate_failure) if ENABLE_FAILURE_SIMULATION else {}
    fallback_attempts = 0
    for index, api_key in enumerate(LLM_KEYS or ["demo-key-1", "demo-key-2"]):
        key_id = f"key_{index + 1}"
        simulated_status = simulations.get(key_id, simulations.get("*"))
        if simulated_status is not None:
            fallback_attempts += 1
            continue

        try:
            if not os.getenv("LLM_API_KEYS"):
                reply = demo_reply(messages)
                input_tokens = max(1, sum(len(item["content"].split()) for item in messages))
                output_tokens = max(1, len(reply.split()))
            else:
                response = litellm.completion(
                    model=MODEL,
                    messages=messages,
                    api_key=api_key,
                    caching=True,
                    timeout=20,
                )
                reply = response.choices[0].message.content.strip()
                input_tokens, output_tokens = token_count(response)
        except Exception as exc:
            status = getattr(exc, "status_code", getattr(exc, "http_status", None))
            is_provider_failure = status in {429, 500, 502, 503} or "429" in str(exc) or "quota" in str(exc).lower()
            logger.warning(
                "provider request failed key_id=%s status=%s error_type=%s",
                key_id,
                status,
                type(exc).__name__,
            )
            if is_provider_failure:
                fallback_attempts += 1
                continue
            fallback_attempts += 1
            continue

        if not reply:
            fallback_attempts += 1
            continue

        latency = int((time.perf_counter() - started) * 1000)
        if latency < 1:
            latency = 1
        metadata = {
            "resolution_source": "LIVE_INFERENCE",
            "model": MODEL,
            "latency_ms": latency,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "key_id": key_id,
            "fallback_attempts": fallback_attempts,
        }
        add_message(session_id, "user", message)
        add_message(session_id, "assistant", reply, metadata)
        store_cached(key, reply, MODEL, input_tokens, output_tokens)
        return {"session_id": session_id, "reply": reply, "metadata": metadata}

    raise HTTPException(status_code=503, detail="all providers unavailable")


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    with connect() as connection:
        rows = connection.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="session not found")

    messages = []
    for row in rows:
        item = {"role": row["role"], "content": row["content"]}
        if row["role"] == "assistant" and row["metadata"]:
            full_metadata = json.loads(row["metadata"])
            item["metadata"] = {
                "resolution_source": full_metadata["resolution_source"],
                "input_tokens": full_metadata["input_tokens"],
                "output_tokens": full_metadata["output_tokens"],
            }
        messages.append(item)
    return {"session_id": session_id, "messages": messages}
