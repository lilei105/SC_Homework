"""
百度 PaddleOCR-VL API 封装

文档解析（PaddleOCR-VL）API 为异步接口：
1. 提交任务获取 task_id
2. 轮询任务状态
3. 成功后从 markdown_url 下载结果
"""
import httpx
import asyncio
import base64
import logging
from typing import Optional, Tuple
from pathlib import Path
from urllib.parse import urlencode

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class BaiduOCRService:
    """百度 PaddleOCR-VL 文档解析服务"""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.baidu_ocr_api_key
        self.secret_key = settings.baidu_ocr_secret_key
        self.base_url = settings.baidu_ocr_base_url
        self.poll_interval = settings.ocr_poll_interval
        self.poll_timeout = settings.ocr_poll_timeout

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def get_access_token(self) -> str:
        """获取百度 API Access Token"""
        if self._access_token and asyncio.get_event_loop().time() < self._token_expires_at:
            return self._access_token

        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, params=params)
            response.raise_for_status()
            data = response.json()

            self._access_token = data["access_token"]
            # Token 有效期通常为 30 天，设置提前 1 小时过期
            expires_in = data.get("expires_in", 2592000)
            self._token_expires_at = asyncio.get_event_loop().time() + expires_in - 3600

            logger.info("Successfully obtained Baidu OCR access token")
            return self._access_token

    async def submit_pdf_task(self, file_content: bytes, filename: str) -> str:
        """
        提交 PDF OCR 任务

        Args:
            file_content: PDF 文件的二进制内容
            filename: 文件名

        Returns:
            task_id: 任务 ID，用于后续轮询
        """
        access_token = await self.get_access_token()
        url = f"{self.base_url}/task?access_token={access_token}"

        # Base64 编码文件内容
        file_data = base64.b64encode(file_content).decode("utf-8")

        data = {
            "file_data": file_data,
            "file_name": filename,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, data=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("error_code"):
                raise Exception(f"Baidu OCR error: {result.get('error_msg')}")

            task_id = result["result"]["task_id"]
            logger.info(f"Submitted OCR task: {task_id}")
            return task_id

    async def query_task_status(self, task_id: str) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
        """
        查询任务状态

        Args:
            task_id: 任务 ID

        Returns:
            (status, markdown_url, parse_result_url, error_msg):
                status: "pending" | "processing" | "success" | "failed"
                markdown_url: Markdown 结果下载地址
                parse_result_url: JSON 结果下载地址（含页面信息）
                error_msg: 失败时的错误信息
        """
        access_token = await self.get_access_token()
        url = f"{self.base_url}/task/query?access_token={access_token}"

        data = {"task_id": task_id}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, data=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("error_code"):
                return "failed", None, None, result.get("error_msg")

            task_result = result.get("result", {})
            status = task_result.get("status", "pending")
            markdown_url = task_result.get("markdown_url")
            parse_result_url = task_result.get("parse_result_url")
            task_error = task_result.get("task_error")

            return status, markdown_url, parse_result_url, task_error

    async def query_task_status_old(self, task_id: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        查询任务状态

        Args:
            task_id: 任务 ID

        Returns:
            (status, markdown_url, error_msg):
                status: "pending" | "processing" | "success" | "failed"
                markdown_url: 成功时的结果下载地址
                error_msg: 失败时的错误信息
        """
        access_token = await self.get_access_token()
        url = f"{self.base_url}/task/query?access_token={access_token}"

        data = {"task_id": task_id}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, data=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("error_code"):
                return "failed", None, result.get("error_msg")

            task_result = result.get("result", {})
            status = task_result.get("status", "pending")
            markdown_url = task_result.get("markdown_url")
            task_error = task_result.get("task_error")

            return status, markdown_url, task_error

    async def poll_task_status(
        self,
        task_id: str,
        timeout: Optional[int] = None,
        interval: Optional[int] = None,
        status_callback=None
    ) -> Tuple[str, Optional[str]]:
        """
        轮询任务状态直到完成或超时

        Args:
            task_id: 任务 ID
            timeout: 超时秒数，默认使用配置值
            interval: 轮询间隔秒数，默认使用配置值
            status_callback: 状态回调函数

        Returns:
            (status, markdown_url):
                status: "success" | "failed" | "timeout"
                markdown_url: 成功时的结果下载地址
        """
        timeout = timeout or self.poll_timeout
        interval = interval or self.poll_interval

        start_time = asyncio.get_event_loop().time()

        while True:
            status, markdown_url, parse_result_url, error = await self.query_task_status(task_id)

            if status_callback:
                await status_callback(status, error)

            if status == "success":
                logger.info(f"OCR task {task_id} completed successfully")
                return "success", markdown_url, parse_result_url

            if status == "failed":
                logger.error(f"OCR task {task_id} failed: {error}")
                return "failed", None, None

            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.warning(f"OCR task {task_id} polling timeout after {elapsed}s")
                return "timeout", None, None

            logger.debug(f"OCR task {task_id} status: {status}, waiting {interval}s...")
            await asyncio.sleep(interval)

    async def download_markdown(self, markdown_url: str) -> str:
        """
        下载 Markdown 结果

        Args:
            markdown_url: 结果下载地址

        Returns:
            Markdown 内容
        """
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(markdown_url)
            response.raise_for_status()
            return response.text

    async def download_json_result(self, parse_result_url: str) -> dict:
        """
        下载 JSON 结果（包含页面信息）

        Args:
            parse_result_url: JSON 结果下载地址

        Returns:
            JSON 解析后的字典
        """
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(parse_result_url)
            response.raise_for_status()
            return response.json()

    async def process_pdf(
        self,
        file_path: Path,
        status_callback=None
    ) -> Tuple[str, dict]:
        """
        完整的 PDF 处理流程

        Args:
            file_path: PDF 文件路径
            status_callback: 状态回调函数

        Returns:
            (markdown_content, json_result): Markdown 内容和 JSON 结果
        """
        # 读取文件
        file_content = file_path.read_bytes()
        filename = file_path.name

        logger.info(f"Processing PDF: {filename} ({len(file_content)} bytes)")

        # 提交任务
        if status_callback:
            await status_callback("submitting", None)

        task_id = await self.submit_pdf_task(file_content, filename)

        # 轮询状态
        async def poll_callback(status, error):
            if status_callback:
                await status_callback(f"ocr_{status}", error)

        final_status, markdown_url, parse_result_url = await self.poll_task_status(
            task_id,
            status_callback=poll_callback
        )

        if final_status != "success":
            raise Exception(f"OCR processing failed with status: {final_status}")

        if not markdown_url:
            raise Exception("OCR completed but no markdown_url returned")

        # 下载结果
        if status_callback:
            await status_callback("downloading", None)

        markdown_content = await self.download_markdown(markdown_url)
        logger.info(f"Downloaded markdown content: {len(markdown_content)} chars")

        # 下载 JSON 结果（包含页面信息）
        json_result = {}
        if parse_result_url:
            try:
                json_result = await self.download_json_result(parse_result_url)
                logger.info(f"Downloaded JSON result: {len(json_result.get('pages', []))} pages")
            except Exception as e:
                logger.warning(f"Failed to download JSON result: {e}")

        return markdown_content, json_result


# 单例
_ocr_service: Optional[BaiduOCRService] = None


def get_ocr_service() -> BaiduOCRService:
    """获取 OCR 服务实例"""
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = BaiduOCRService()
    return _ocr_service
