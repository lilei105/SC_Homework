#!/usr/bin/env python3
"""
将 chunks.jsonl 转换为后端期望的 DocumentSchema JSON 格式

Usage:
    python scripts/convert_chunks_to_schema.py <chunks.jsonl> [--output document.json]
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any


def convert_chunks_to_schema(chunks_path: str, output_path: str = None) -> dict:
    """将 chunks.jsonl 转换为 DocumentSchema 格式"""

    # 读取所有 chunks
    chunks = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    if not chunks:
        raise ValueError("No chunks found in input file")

    # 提取文档元数据（从第一个 chunk）
    document_id = chunks[0].get("document_id", "unknown_doc")

    # 构建 sections 映射
    sections_map: Dict[str, Dict] = {}  # section_path_str -> section_info

    for i, chunk in enumerate(chunks):
        section_path = chunk.get("section_path", [])
        if not section_path:
            continue

        # level-1 section
        level1_title = section_path[0] if len(section_path) > 0 else "Unknown"
        level2_title = section_path[1] if len(section_path) > 1 else None

        # 创建 level-1 section
        level1_id = f"sec_{level1_title.lower().replace(' ', '_')[:30]}"
        if level1_id not in sections_map:
            sections_map[level1_id] = {
                "section_id": level1_id,
                "title": level1_title,
                "normalized_title": level1_title,
                "summary": None,
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "children": []
            }

        # 更新 level-1 的页码范围
        if chunk.get("page_start"):
            if sections_map[level1_id]["page_start"] is None or chunk["page_start"] < sections_map[level1_id]["page_start"]:
                sections_map[level1_id]["page_start"] = chunk["page_start"]
        if chunk.get("page_end"):
            if sections_map[level1_id]["page_end"] is None or chunk["page_end"] > sections_map[level1_id]["page_end"]:
                sections_map[level1_id]["page_end"] = chunk["page_end"]

        # 创建 level-2 section
        if level2_title:
            level2_id = f"{level1_id}_{i:04d}"

            # 检查是否已存在相同 level2
            existing_level2 = None
            for child in sections_map[level1_id]["children"]:
                if child["title"] == level2_title:
                    existing_level2 = child
                    break

            if existing_level2:
                # 更新页码范围
                if chunk.get("page_start") and (existing_level2["page_start"] is None or chunk["page_start"] < existing_level2["page_start"]):
                    existing_level2["page_start"] = chunk["page_start"]
                if chunk.get("page_end") and (existing_level2["page_end"] is None or chunk["page_end"] > existing_level2["page_end"]):
                    existing_level2["page_end"] = chunk["page_end"]
            else:
                # 创建新的 level-2 section
                sections_map[level1_id]["children"].append({
                    "section_id": level2_id,
                    "title": level2_title,
                    "normalized_title": level2_title,
                    "summary": None,
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                })

    # 构建 chunks 列表（转换为 DocumentSchema 格式）
    schema_chunks = []
    for i, chunk in enumerate(chunks):
        section_path = chunk.get("section_path", [])
        level1_title = section_path[0] if len(section_path) > 0 else "Unknown"
        level2_title = section_path[1] if len(section_path) > 1 else level1_title

        level1_id = f"sec_{level1_title.lower().replace(' ', '_')[:30]}"

        # 映射 chunk_type
        original_type = chunk.get("chunk_type", "narrative")
        type_mapping = {
            "narrative": "text",
            "table_heavy": "table",
            "kpi": "table",
            "mixed_media": "mixed",
            "appendix": "text",
            "risk_disclosure": "text"
        }
        mapped_type = type_mapping.get(original_type, "text")

        schema_chunk = {
            "chunk_id": chunk.get("chunk_id", f"chunk_{i:04d}"),
            "chunk_index": i,
            "section_id": level1_id,
            "section_title": " > ".join(section_path) if section_path else "Unknown",
            "section_summary": None,
            "page_start": chunk.get("page_start", 1),
            "page_end": chunk.get("page_end", 1),
            "chunk_type": mapped_type,
            "content": chunk.get("content", ""),
            "content_brief": chunk.get("content", "")[:200] + "..." if len(chunk.get("content", "")) > 200 else chunk.get("content", ""),
            "keywords": [],
            "period": None,
            "entities": None,
            "table_data": None,
            "figure_data": None,
            "financial_metrics": [],
            "source_trace": None,
            "relations": {
                "prev_chunk_id": chunks[i-1].get("chunk_id") if i > 0 else None,
                "next_chunk_id": chunks[i+1].get("chunk_id") if i < len(chunks) - 1 else None
            },
            "bundle_id": None,
            "flags": {
                "is_section_lead": False,
                "is_table_title": False,
                "is_table_continuation": False,
                "is_figure_caption": False,
                "is_key_financial_chunk": original_type in ["kpi", "table_heavy"]
            }
        }
        schema_chunks.append(schema_chunk)

    # 构建 sections 列表（扁平化）
    sections_list = []
    for section_id, section_data in sections_map.items():
        children = section_data.pop("children", [])
        sections_list.append(section_data)
        # 也添加 level-2 sections
        for child in children:
            sections_list.append(child)

    # 计算文档级信息
    all_pages = [c.get("page_start", 1) for c in chunks if c.get("page_start")]
    max_page = max(all_pages) if all_pages else 1

    # 构建最终文档
    document = {
        "schema_version": "1.0",
        "document": {
            "document_id": document_id,
            "source_file": f"{document_id}.pdf",
            "company_name": "Standard Chartered",
            "ticker": "STAN",
            "report_type": "annual_report",
            "report_title": "Standard Chartered Annual Report 2025",
            "language": "en",
            "currency": "USD",
            "fiscal_year": 2025,
            "fiscal_period": "FY",
            "report_date": "2025-03-01",
            "page_count": max_page,
            "parser": {
                "provider": "chunking_pipeline",
                "version": "1.0",
                "notes": "Converted from chunks.jsonl"
            }
        },
        "sections": sections_list,
        "chunks": schema_chunks
    }

    return document


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    chunks_path = sys.argv[1]
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    if not output_path:
        # 默认输出到同一目录
        output_path = Path(chunks_path).parent / "document_schema.json"

    print(f"Converting {chunks_path} to DocumentSchema format...")
    document = convert_chunks_to_schema(chunks_path, output_path)

    print(f"Writing to {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary ===")
    print(f"Document ID: {document['document']['document_id']}")
    print(f"Company: {document['document']['company_name']}")
    print(f"Total chunks: {len(document['chunks'])}")
    print(f"Total sections: {len(document['sections'])}")
    print(f"Page count: {document['document']['page_count']}")


if __name__ == "__main__":
    main()
