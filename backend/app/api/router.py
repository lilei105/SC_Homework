from fastapi import APIRouter
from app.api.endpoints import documents, chat

api_router = APIRouter()

api_router.include_router(documents.router, prefix="/v1")
api_router.include_router(chat.router, prefix="/v1")
