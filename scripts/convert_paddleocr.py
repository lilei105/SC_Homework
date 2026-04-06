#!/usr/bin/env python3
"""
PaddleOCR JSON to Financial RAG Schema 转换工具

Usage:
    python scripts/convert_paddleocr.py <input_json> <output_json> [--company "Company Name"] [--fiscal-year 2024]

"""
import json
import re
import sys
import uuid
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Optional


# 需要忽略的 block_label 类型
IGNORE_LABELS = {"header_image", "footer", "footer_image", "header", "aside_text", "vision_footnote"}

# block_label 到 chunk_type 的映射
LABEL_TO_CHUNK_TYPE = {
    "text": "text",
    "paragraph_title": "text",
    "content": "text",
    "table": "table",
    "image": "figure",
    "chart": "figure",
    "seal": "figure",
}


def parse_html_table(html_content: str) -> Optional[dict]:
    """
    解析 HTML 表格,返回 table_data 结构

    Returns:
        {
            "table_title": None,
            "unit": None,
            "headers": [...],
            "rows": [...]
        } or None
    """
    if not html_content or "<table" not in html_content:
        return None

    try:
        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table")
        if not table:
            return None

        rows = table.find_all("tr")
        if not rows:
            return None

        # 提取 headers
        headers = []
        data_rows = []

        for i, row in enumerate(rows):
            cells = row.find_all("td")
            row_data = [cell.get_text(strip=True) for cell in cells]

            if i == 0:
                headers = row_data
            else:
                data_rows.append(row_data)

        # 如果没有明确的 headers(第一行也是数据)
        if not headers or all(h == "" for h in headers):
            if data_rows:
                headers = [f"Column {i+1}" for i in range(len(data_rows[0]))]
            else:
                headers = []

        return {
            "table_title": None,
            "unit": None,
            "headers": headers,
            "rows": data_rows
        }
    except Exception as e:
        print(f"Warning: Failed to parse HTML table: {e}")
        return None


def table_to_natural_language(table_data: dict) -> str:
    """
    将表格转换为自然语言描述

    用于 RAG 检索的 content 字段
    """
    headers = table_data.get("headers", [])
    rows = table_data.get("rows", [])

    if not headers or not rows:
        return ""

    lines = []
    for row in rows:
        pairs = []
        for i, cell in enumerate(row):
            if i < len(headers):
                header = headers[i] if i < len(headers) else f"Column {i}"
                pairs.append(f"{header}: {cell}")
        lines.append(", ".join(pairs))

    return "; ".join(lines)


def clean_text(text: str) -> str:
    """清理文本,去除多余空白"""
    if not text:
        return ""
    # 去除多余换行
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 去除首尾空白
    text = text.strip()
    return text


def convert_paddleocr_to_schema(
    input_path: str,
    output_path: str,
    company_name: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    report_type: str = "annual_report"
) -> dict:
    """
    转换 PaddleOCR JSON 到 Financial RAG Schema

    Args:
        input_path: PaddleOCR JSON 文件路径
        output_path: 输出 JSON 文件路径
        company_name: 公司名称 (可选, 会尝试从内容推断)
        fiscal_year: 财年 (可选, 会尝试从内容推断)
        report_type: 报告类型

    Returns:
        生成的 schema 字典
    """
    print(f"Reading PaddleOCR JSON from {input_path}...")

    with open(input_path, "r", encoding="utf-8") as f:
        paddleocr_data = json.load(f)

    print(f"Total pages: {len(paddleocr_data)}")

    # 收集所有 chunks
    all_chunks = []
    chunk_index = 0

    # 用于推断文档信息的正则
    year_pattern = re.compile(r'\b(20[0-9]{2}|202[0-9])\b')

    # 遍历每一页
    for page_idx in range(1, len(paddleocr_data) + 1):
        page_data = paddleocr_data[page_idx - 1]

        # 获取 parsing_res_list
        pruned_result = page_data.get("prunedResult", {})
        parsing_res_list = pruned_result.get("parsing_res_list", [])

        if not parsing_res_list:
            continue

        # 遍历每个 block
        for block in parsing_res_list:
            block_label = block.get("block_label", "")
            block_content = block.get("block_content", "")

            # 跳过忽略的类型
            if block_label in IGNORE_LABELS:
                continue

            # 映射到 chunk_type
            chunk_type = LABEL_TO_CHUNK_TYPE.get(block_label, "text")

            # 清理内容
            content = clean_text(block_content)

            # 尝试推断财年
            if fiscal_year is None:
                year_match = year_pattern.search(content)
                if year_match:
                    fiscal_year = int(year_match.group(1))

            # 尝试推断公司名 (从标题中)
            if company_name is None and block_label == "paragraph_title":
                # 查找可能的标题模式
                title_patterns = [
                    r'(.+?)\s+(?:Annual Report|10-K|Form 10K)',
                    r'(.+?)\s+Corporation',
                ]
                for pattern in title_patterns:
                    match = re.search(pattern, content, re.IGNORECASE)
                    if match:
                        company_name = match.group(1).strip()
                        break

            # 处理表格
            table_data = None
            if block_label == "table":
                table_data = parse_html_table(block_content)
                if table_data:
                    # 转换为自然语言
                    content = table_to_natural_language(table_data)
                else:
                    # 保留原始 markdown 格式
                    content = block_content

            # 生成 chunk
            chunk_id = f"c{uuid.uuid4().hex[:8]}"

            chunk = {
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "section_id": None,  # 简化版不划分章节
                "section_title": None,
                "section_summary": None,
                "page_start": page_idx,
                "page_end": page_idx,
                "chunk_type": chunk_type,
                "content": content,
                "content_brief": None,  # 后续可用 LLM 生成
                "keywords": [],  # 后续可用 LLM 生成
                "period": {
                    "fiscal_year": fiscal_year,
                    "fiscal_period": "FY",
                    "date_label": f"FY{fiscal_year}" if fiscal_year else None,
                    "start_date": None,
                    "end_date": None
                },
                "entities": {
                    "company": [company_name] if company_name else [],
                    "products": [],
                    "regions": [],
                    "people": []
                },
                "table_data": table_data,
                "figure_data": None,
                "financial_metrics": [],  # 后续可提取
                "source_trace": {
                    "source_block_ids": [f"p{page_idx}_b{block.get('block_id', '')}"],
                    "raw_text_excerpt": block_content[:200] if block_content else None,
                    "ocr_confidence": None
                },
                "relations": {
                    "prev_chunk_id": None,
                    "next_chunk_id": None
                },
                "bundle_id": None,
                "flags": {
                    "is_section_lead": block_label == "paragraph_title",
                    "is_table_title": False,
                    "is_table_continuation": False,
                    "is_figure_caption": False,
                    "is_key_financial_chunk": block_label == "table"
                }
            }

            all_chunks.append(chunk)
            chunk_index += 1

    # 构建文档元数据
    document_id = Path(input_path).stem
    if company_name is None:
        company_name = "Unknown Company"
    if fiscal_year is None:
        fiscal_year = 2025  # 默认值

    document = {
        "document_id": document_id,
        "source_file": Path(input_path).name,
        "company_name": company_name,
        "ticker": None,
        "report_type": report_type,
        "report_title": f"{company_name} Annual Report {fiscal_year}",
        "language": "en",
        "currency": "USD",
        "fiscal_year": fiscal_year,
        "fiscal_period": "FY",
        "report_date": None,
        "page_count": len(paddleocr_data),
        "parser": {
            "provider": "PaddleOCR-VL-1.5",
            "version": None,
            "notes": "Converted from PaddleOCR JSON output"
        }
    }

    # 构建最终 schema
    schema = {
        "schema_version": "1.0",
        "document": document,
        "sections": [],  # 简化版不划分章节
        "chunks": all_chunks
    }

    # 更新 chunk relations
    for i in range(len(all_chunks)):
        if i > 0:
            all_chunks[i]["relations"]["prev_chunk_id"] = all_chunks[i-1]["chunk_id"]
        if i < len(all_chunks) - 1:
            all_chunks[i]["relations"]["next_chunk_id"] = all_chunks[i+1]["chunk_id"]

    print(f"Total chunks: {len(all_chunks)}")
    print(f"Writing to {output_path}...")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)

    print("Conversion completed!")

    return schema


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    company_name = sys.argv[3] if len(sys.argv) > 3 else None
    fiscal_year = int(sys.argv[4]) if len(sys.argv) > 4 else None

    convert_paddleocr_to_schema(
        input_path=input_path,
        output_path=output_path,
        company_name=company_name,
        fiscal_year=fiscal_year
    )


if __name__ == "__main__":
    main()
