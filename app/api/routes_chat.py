from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import ChatRequest, ChatResponse
from app.core.database import get_db
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    service = ChatService(db)
    result = service.answer(query=request.query, top_k=request.top_k, request_tag="api")
    return ChatResponse(**result)
