from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain.tools import tool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from . import database

SYSTEM_PROMPT = """You are a patient benefits assistant for a hospital network.

Your job:
1. Read the patient's symptoms.
2. Use calculate_patient_options to determine the specialty, insurance details, hospital options, patient cost, and insurer coverage.
3. Explain the best hospital economically and list useful alternatives.

Rules:
- Do not invent hospitals, prices, insurance benefits, or coverage.
- Money values must come from tool results only.
- Do not diagnose. Suggest a general specialty.
- If symptoms sound urgent, tell the patient to seek emergency care immediately.
- Respond in the same language as the patient when practical.
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
    _CHECKPOINT_CONN = await aiosqlite.connect(checkpoint_path)
    return AsyncSqliteSaver(_CHECKPOINT_CONN)


async def get_agent() -> Any:
    global _AGENT
    if _AGENT is not None:
        return _AGENT
    model_name = os.getenv("AGENT_MODEL", "ollama:devstral-2")
    model = init_chat_model(model_name, temperature=0.2, timeout=300, max_tokens=4000)
    _AGENT = create_deep_agent(
        model=model,
        tools=[calculate_patient_options, get_user_insurance],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=await _get_checkpointer(),
    )
    return _AGENT


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
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
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
    recommendation = database.calculate_best_option(user_id=user_id, symptoms=message)
    deep_agent = await get_agent()
    result = await deep_agent.ainvoke(_input(user_id, message), config=_config(thread_id))
    text = _final_text(result) if isinstance(result, dict) else str(result)
    if not text:
        raise RuntimeError("Agent returned an empty response")
    return text, recommendation


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(_jsonable(data), ensure_ascii=False)}\n\n"


async def stream_agent(user_id: int, thread_id: str, message: str) -> AsyncIterator[str]:
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
    except Exception as exc:
        yield sse("error", {"message": str(exc)})
        return

    if not final_text:
        yield sse("error", {"message": "Agent returned an empty response"})
        return

    yield sse("result", {"message": final_text, "recommendation": recommendation})
