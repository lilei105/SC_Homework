"""
将 PaddleOCR-VL JSON 文件导入到系统中

用法：
    cd backend && python ../scripts/import_paddleocr.py
"""
import json
import sys
import os
import uuid
from pathlib import Path
from datetime import datetime

# 添加 backend 目录到 Python 路径
backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

# 设置环境变量（如果需要）
os.environ.setdefault("QDRANT_PATH", "./data/qdrant_storage")


def extract_markdown_from_paddleocr(data: list) -> str:
    """从 PaddleOCR-VL JSON 中提取 markdown 内容，带页码标记"""
    markdown_parts = []

    for i, page_data in enumerate(data):
        page_num = i + 1
        pruned = page_data.get("prunedResult", {})

        # 优先使用 markdown 字段
        page_markdown = pruned.get("markdown", "")

        if not page_markdown:
            # 如果没有 markdown，从 parsing_res_list 构建
            blocks = pruned.get("parsing_res_list", [])
            block_contents = []
            for block in blocks:
                content = block.get("block_content", "")
                if content:
                    block_contents.append(content)
            page_markdown = "\n\n".join(block_contents)

        if page_markdown.strip():
            markdown_parts.append(f"<!-- PAGE: {page_num} -->\n{page_markdown.strip()}")

    return "\n\n".join(markdown_parts)


def extract_page_dict_from_paddleocr(data: list) -> dict:
    """从 PaddleOCR-VL JSON 中提取页面字典"""
    page_dict = {}

    for i, page_data in enumerate(data):
        page_num = i + 1
        pruned = page_data.get("prunedResult", {})

        # 从 parsing_res_list 提取纯文本
        blocks = pruned.get("parsing_res_list", [])
        text_parts = []
        for block in blocks:
            label = block.get("block_label", "")
            content = block.get("block_content", "")
            if content and label not in ["image", "header", "footer"]:
                # 简单清理 HTML 标签
                import re
                clean_content = re.sub(r'<[^>]+>', '', content)
                text_parts.append(clean_content)

        page_dict[page_num] = "\n\n".join(text_parts)

    return page_dict


def get_company_info(filename: str) -> dict:
    """从文件名提取公司信息"""
    base = filename.replace(".pdf_by_PaddleOCR-VL-1.5.json", "")

    company_map = {
        "Tesla_2024_10K_Annual_Report": {
            "document_id": "tesla_2024_10k",
            "company_name": "Tesla, Inc.",
            "ticker": "TSLA",
            "currency": "USD",
            "language": "en",
            "report_type": "10k",
            "report_title": "Tesla, Inc. Form 10-K Annual Report 2024",
            "fiscal_year": 2024,
        },
        "BP_2025_Annual_Report": {
            "document_id": "bp_2025_annual",
            "company_name": "BP p.l.c.",
            "ticker": "BP",
            "currency": "GBP",
            "language": "en",
            "report_type": "annual_report",
            "report_title": "BP Annual Report 2025",
            "fiscal_year": 2025,
        },
        "StandardChartered_2025_Annual_Report": {
            "document_id": "standard_chartered_2025_annual",
            "company_name": "Standard Chartered PLC",
            "ticker": "2888.HK",
            "currency": "USD",
            "language": "en",
            "report_type": "annual_report",
            "report_title": "Standard Chartered Annual Report 2025",
            "fiscal_year": 2025,
        },
        "PingAn_2025_Annual_Report": {
            "document_id": "pingan_2025_annual",
            "company_name": "中国平安保险（集团）股份有限公司",
            "ticker": "601318.SH",
            "currency": "CNY",
            "language": "zh",
            "report_type": "annual_report",
            "report_title": "中国平安2025年年度报告",
            "fiscal_year": 2025,
        },
    }

    for key, info in company_map.items():
        if key in base:
            return info

    # 默认信息
    return {
        "document_id": base.lower().replace(" ", "_")[:30],
        "company_name": base.replace("_", " "),
        "ticker": None,
        "currency": "USD",
        "language": "en",
        "report_type": "annual_report",
        "report_title": f"{base} Annual Report",
        "fiscal_year": 2024,
    }


def import_file(json_path: Path) -> bool:
    """导入单个文件"""
    print(f"\n{'='*60}")
    print(f"Processing: {json_path.name}")

    # 读取 JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"  Pages: {len(data)}")

    # 提取 markdown 和页面字典
    markdown = extract_markdown_from_paddleocr(data)
    page_dict = extract_page_dict_from_paddleocr(data)
    print(f"  Markdown: {len(markdown)} chars, {len(page_dict)} pages")

    # 获取公司信息
    metadata = get_company_info(json_path.name)
    document_id = metadata["document_id"]
    print(f"  Document ID: {document_id}")
    print(f"  Company: {metadata['company_name']}")

    # 调用 chunker
    print("  Chunking...")
    from app.services.chunker import get_chunker
    chunker = get_chunker()

    doc_schema, intermediate = chunker.process_markdown(
        markdown,
        metadata,
        ocr_json_result={"pages": [{"page_num": k-1, "text": v} for k, v in page_dict.items()]},
        save_intermediate=None
    )

    print(f"  Chunks: {len(doc_schema.chunks)}")
    print(f"  Sections: {len(doc_schema.sections)}")

    # 索引到 Qdrant
    print("  Indexing to Qdrant...")
    from app.services.indexer import index_document
    index_document(doc_schema)

    print(f"  ✓ Done!")
    return True


def main():
    project_root = Path(__file__).parent.parent
    sample_dir = project_root / "pdf_sample"

    if not sample_dir.exists():
        print(f"Error: Directory not found: {sample_dir}")
        return

    json_files = list(sample_dir.glob("*_by_PaddleOCR-VL-*.json"))

    if not json_files:
        print(f"No PaddleOCR-VL JSON files found in {sample_dir}")
        return

    print(f"Found {len(json_files)} PaddleOCR-VL JSON files")
    for f in sorted(json_files):
        print(f"  - {f.name}")

    success = 0
    for json_path in sorted(json_files):
        try:
            if import_file(json_path):
                success += 1
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"Completed: {success}/{len(json_files)} files imported")


if __name__ == "__main__":
    main()
