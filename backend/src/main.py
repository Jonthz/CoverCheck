from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

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


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database.init_db()
    yield


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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/users", response_model=list[UserSummary])
def users() -> list[dict]:
    return database.get_users()


@app.get("/users/{user_id}")
def user(user_id: int) -> dict:
    item = database.get_user(user_id)
    if not item:
        raise HTTPException(status_code=404, detail="User not found")
    return item


@app.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user_id: int) -> list[dict]:
    if not database.get_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    return database.list_conversations(user_id)


@app.post("/conversations", response_model=ConversationResponse)
def conversations(payload: ConversationCreate) -> ConversationResponse:
    try:
        item = database.create_conversation(payload.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConversationResponse(conversation_id=item["conversation_id"], user_id=item["user_id"])


@app.get("/conversations/{conversation_id}/messages", response_model=list[StoredMessage])
def messages(conversation_id: str) -> list[dict]:
    if not database.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return database.get_messages(conversation_id)


@app.post("/conversations/{conversation_id}/messages", response_model=ChatResponse)
async def chat(conversation_id: str, payload: MessageRequest) -> ChatResponse:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    database.add_message(conversation_id, "assistant", text, {"recommendation": recommendation})
    return ChatResponse(message=text, recommendation=recommendation)


@app.post("/conversations/{conversation_id}/messages/stream")
async def chat_stream(conversation_id: str, payload: MessageRequest) -> StreamingResponse:
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
            database.add_message(
                conversation_id,
                "assistant",
                final_message,
                {"recommendation": final_recommendation},
            )

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
