from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, database
from .schemas import (
    ChatResponse,
    ConversationCreate,
    ConversationResponse,
    ConversationSummary,
    HealthResponse,
    MessageRequest,
    StoredMessage,
    UserSummary,
)
from .settings import ENV_PATH, load_environment


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)
load_environment()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Starting backend with env path %s", ENV_PATH)
    database.init_db()
    logger.info("Backend startup complete")
    yield
    logger.info("Backend shutdown complete")


app = FastAPI(title="Copay Coverage Agent API", version="0.1.0", lifespan=lifespan)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/health/model")
async def model_health() -> dict:
    logger.info("Checking model health")
    try:
        return await agent.check_model_health()
    except Exception as exc:
        logger.exception("Model health check failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/users", response_model=list[UserSummary])
def users() -> list[dict]:
    logger.info("Listing users")
    return database.get_users()


@app.get("/users/{user_id}")
def user(user_id: int) -> dict:
    logger.info("Fetching user_id=%s", user_id)
    item = database.get_user(user_id)
    if not item:
        raise HTTPException(status_code=404, detail="User not found")
    return item


@app.get("/users/{user_id}/insurance")
def user_insurance(user_id: int) -> dict:
    logger.info("Fetching insurance for user_id=%s", user_id)
    item = database.get_user_insurance(user_id)
    if not item:
        raise HTTPException(status_code=404, detail="User not found")
    return item


@app.get("/users/{user_id}/coverage")
def user_coverage(user_id: int) -> list[dict]:
    logger.info("Fetching coverage grid for user_id=%s", user_id)
    try:
        return database.list_user_coverage(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/hospitals")
def hospitals() -> list[dict]:
    logger.info("Listing hospitals")
    return database.list_hospitals()


@app.get("/specialties")
def specialties() -> list[dict]:
    logger.info("Listing specialties")
    return database.list_specialties()


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user_id: int) -> list[dict]:
    logger.info("Listing conversations for user_id=%s", user_id)
    if not database.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return database.list_conversations(user_id)


@app.post("/conversations", response_model=ConversationResponse)
def conversations(payload: ConversationCreate) -> ConversationResponse:
    logger.info("Creating conversation for user_id=%s", payload.user_id)
    try:
        item = database.create_conversation(payload.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConversationResponse(conversation_id=item["conversation_id"], user_id=item["user_id"])


@app.get("/conversations/{conversation_id}/messages", response_model=list[StoredMessage])
def messages(conversation_id: str) -> list[dict]:
    logger.info("Fetching messages for conversation_id=%s", conversation_id)
    if not database.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return database.get_messages(conversation_id)


@app.delete("/users/{user_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(user_id: int, conversation_id: str) -> None:
    logger.info("Deleting conversation_id=%s for user_id=%s", conversation_id, user_id)
    if not database.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    if not database.delete_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@app.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def chat(conversation_id: str, payload: MessageRequest) -> ChatResponse:
    logger.info("Received non-streaming chat message for conversation_id=%s", conversation_id)
    conversation = database.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    database.add_message(conversation_id, "user", payload.message)
    try:
        text, recommendation = await agent.run_agent(
            user_id=conversation["user_id"],
            thread_id=conversation["thread_id"],
            message=payload.message,
        )
    except ValueError as exc:
        logger.exception("Non-streaming chat failed for conversation_id=%s", conversation_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent failed for conversation_id=%s", conversation_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    database.add_message(conversation_id, "assistant", text, {"recommendation": recommendation})
    return ChatResponse(message=text, recommendation=recommendation)


@app.post("/conversations/{conversation_id}/messages/stream")
async def chat_stream(conversation_id: str, payload: MessageRequest) -> StreamingResponse:
    logger.info("Received streaming chat message for conversation_id=%s", conversation_id)
    conversation = database.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    database.add_message(conversation_id, "user", payload.message)

    async def events() -> AsyncIterator[str]:
        final_message = None
        final_recommendation = None
        async for event in agent.stream_agent(
            user_id=conversation["user_id"],
            thread_id=conversation["thread_id"],
            message=payload.message,
        ):
            if event.startswith("event: result"):
                import json

                data = json.loads(event.split("data: ", 1)[1])
                final_message = data.get("message")
                final_recommendation = data.get("recommendation")
            yield event
        if final_message:
            logger.info("Persisting streamed assistant message for conversation_id=%s", conversation_id)
            database.add_message(
                conversation_id,
                "assistant",
                final_message,
                {"recommendation": final_recommendation},
            )
        else:
            logger.warning("No final streamed assistant message for conversation_id=%s", conversation_id)

    return StreamingResponse(events(), media_type="text/event-stream")


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}")
    def frontend_fallback(path: str) -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")
