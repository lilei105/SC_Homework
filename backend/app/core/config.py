from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional
from pydantic import Field


class Settings(BaseSettings):
    # 阿里云百炼 API 配置
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.comcompatible-mode/v1"
    dashscope_model: str = "qwen-turbo"

    # Qdrant 配置
    qdrant_path: str = "./data/qdrant_storage"
    collection_name: str = "financial_reports"

    # 模型配置
    embedding_model_name: str = "BAAI/bge-m3"
    reranker_model_name: str = "BAAI/bge-reranker-v2-gemma"
    llm_model: str = "qwen-turbo"

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
