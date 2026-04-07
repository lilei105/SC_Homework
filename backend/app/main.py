import logging
import sys

# 配置日志 - 确保输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
# 设置 uvicorn 日志级别
logging.getLogger("uvicorn").setLevel(logging.INFO)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.router import api_router
from app.utils.qdrant_client import init_collection
from app.core.config import get_settings

settings = get_settings()
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize Qdrant collection
    init_collection()
    yield
    # Shutdown: cleanup if needed


app = FastAPI(
    title="Financial RAG API",
    description="API for financial report question answering using RAG",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Financial RAG API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
