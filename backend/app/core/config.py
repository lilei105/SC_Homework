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

    # 百度 OCR API 配置
    baidu_ocr_api_key: str = ""
    baidu_ocr_secret_key: str = ""
    baidu_ocr_base_url: str = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser"

    # OCR 处理配置
    ocr_max_pages: int = 500       # 最大页数限制
    ocr_max_size_mb: int = 100     # 最大文件大小 MB
    ocr_poll_interval: int = 5     # 轮询间隔秒数
    ocr_poll_timeout: int = 600    # 轮询超时秒数

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
