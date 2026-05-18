from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
from deepagents import create_deep_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from . import database
from .settings import load_environment

logger = logging.getLogger(__name__)
load_environment()

GOOGLE_MODEL = "gemma-4-26b-a4b-it"
MODEL_UNAVAILABLE_MESSAGE = "Could not connect to Google GenAI. Check GOOGLE_API_KEY and model access."

SYSTEM_PROMPT = """You are a patient benefits assistant for a hospital network.

Your job:
1. Read the patient's symptoms.
2. Use calculate_patient_options to determine the specialty, insurance details, hospital options, patient cost, and insurer coverage.
3. Explain the best hospital economically and compare all hospitals returned by the tool.

Rules:
- Do not invent hospitals, prices, insurance benefits, or coverage.
- Money values must come from tool results only.
- Do not diagnose. Suggest a general specialty.
- If symptoms sound urgent, tell the patient to seek emergency care immediately.
- Always respond in Spanish.
- Use the tool's selection_reason and all_options fields.
- Mention every hospital in the comparison, including out-of-network hospitals.
- Explain ties clearly when several hospitals have the same patient cost.
- Return only the final user-facing answer. Do not include internal reasoning,
  thinking traces, JSON-like blocks, plans, or analysis.
"""

_CHECKPOINT_CONN: aiosqlite.Connection | None = None
_AGENT = None


@tool
def calculate_patient_options(user_id: int, symptoms: str) -> dict[str, Any]:
    """Calculate specialty, hospital ranking, patient copay, and insurance coverage."""
    return database.calculate_best_option(user_id=user_id, symptoms=symptoms)


@tool
def get_user_insurance(user_id: int) -> dict[str, Any]:
    """Return the selected user's insurance plan details."""
    user = database.get_user(user_id)
    if not user:
        raise ValueError("User not found")
    return user


async def _get_checkpointer() -> Any:
    global _CHECKPOINT_CONN
    checkpoint_path = Path(__file__).resolve().parents[1] / "agent_checkpoints.sqlite"
    logger.info("Opening async LangGraph checkpoint database at %s", checkpoint_path)
    _CHECKPOINT_CONN = await aiosqlite.connect(checkpoint_path)
    return AsyncSqliteSaver(_CHECKPOINT_CONN)


async def get_agent() -> Any:
    global _AGENT
    if _AGENT is not None:
        return _AGENT
    _require_google_api_key()
    logger.info(
        "Initializing DeepAgent with Google GenAI model=%s api_key_present=%s",
        GOOGLE_MODEL,
        bool(os.getenv("GOOGLE_API_KEY")),
    )
    model = ChatGoogleGenerativeAI(
        model=GOOGLE_MODEL,
        temperature=0.2,
        max_tokens=4000,
    )
    _AGENT = create_deep_agent(
        model=model,
        tools=[calculate_patient_options, get_user_insurance],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=await _get_checkpointer(),
    )
    return _AGENT


def _require_google_api_key() -> None:
    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY is missing from backend/.env")


async def check_model_health() -> dict[str, Any]:
    _require_google_api_key()
    model = ChatGoogleGenerativeAI(
        model=GOOGLE_MODEL,
        temperature=0,
        max_tokens=8,
    )
    try:
        response = await model.ainvoke("Reply with exactly: ok")
    except Exception as exc:
        logger.exception("Google GenAI health check failed")
        raise RuntimeError(MODEL_UNAVAILABLE_MESSAGE) from exc
    return {
        "status": "ok",
        "model": GOOGLE_MODEL,
        "provider": "google-genai",
        "response": _message_text(response),
    }


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _input(user_id: int, message: str) -> dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": f"User id: {user_id}\nPatient message: {message}",
            }
        ]
    }


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, dict) and "content" in content:
        content = content["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(str(item))
                continue
            item_type = item.get("type")
            if item_type in {"thinking", "reasoning"}:
                continue
            if item_type in {None, "text"} and "text" in item:
                parts.append(str(item["text"]))
        return "".join(parts)
    return str(content)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return str(value)


def _final_text(result: dict[str, Any]) -> str:
    messages = result.get("messages") or []
    if not messages:
        return "No pude generar una respuesta."
    return _message_text(messages[-1])


async def run_agent(user_id: int, thread_id: str, message: str) -> tuple[str, dict[str, Any]]:
    logger.info("Running non-streaming agent for user_id=%s thread_id=%s", user_id, thread_id)
    recommendation = database.calculate_best_option(user_id=user_id, symptoms=message)
    deep_agent = await get_agent()
    try:
        result = await deep_agent.ainvoke(_input(user_id, message), config=_config(thread_id))
    except Exception as exc:
        logger.exception("Google GenAI call failed for user_id=%s thread_id=%s", user_id, thread_id)
        raise RuntimeError(MODEL_UNAVAILABLE_MESSAGE) from exc
    text = _final_text(result) if isinstance(result, dict) else str(result)
    if not text:
        raise RuntimeError("Agent returned an empty response")
    return text, recommendation


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(_jsonable(data), ensure_ascii=False)}\n\n"


async def stream_agent(user_id: int, thread_id: str, message: str) -> AsyncIterator[str]:
    logger.info("Starting streaming agent for user_id=%s thread_id=%s", user_id, thread_id)
    yield sse("status", {"message": "Clasificando sintomas"})
    recommendation = database.calculate_best_option(user_id=user_id, symptoms=message)
    yield sse("status", {"message": "Consultando seguro y contratos hospitalarios"})

    final_text = ""
    try:
        deep_agent = await get_agent()
        async for chunk in deep_agent.astream(
            _input(user_id, message),
            config=_config(thread_id),
            stream_mode="updates",
        ):
            yield sse("agent", chunk)
        result = await deep_agent.aget_state(config=_config(thread_id))
        values = getattr(result, "values", {}) or {}
        if isinstance(values, dict):
            final_text = _final_text(values)
    except Exception:
        logger.exception("Google GenAI streaming agent failed for user_id=%s thread_id=%s", user_id, thread_id)
        yield sse("error", {"message": MODEL_UNAVAILABLE_MESSAGE})
        return

    if not final_text:
        logger.error("Streaming agent returned empty response for user_id=%s thread_id=%s", user_id, thread_id)
        yield sse("error", {"message": "Agent returned an empty response"})
        return

    logger.info("Streaming agent completed for user_id=%s thread_id=%s", user_id, thread_id)
    yield sse("result", {"message": final_text, "recommendation": recommendation})
