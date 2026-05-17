from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class UserSummary(BaseModel):
    id: int
    full_name: str
    age: int
    city: str
    insurance_plan: str
    insurance_company: str


class ConversationCreate(BaseModel):
    user_id: int


class ConversationResponse(BaseModel):
    conversation_id: str
    user_id: int


class ConversationSummary(BaseModel):
    conversation_id: str
    user_id: int
    created_at: str
    updated_at: str
    last_message: str | None = None


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    message: str
    recommendation: dict[str, Any] | None = None


class StoredMessage(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any]
    created_at: str
