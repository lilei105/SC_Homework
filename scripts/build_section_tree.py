#!/usr/bin/env python3
"""
构造章节树：根据目录结构划分全文内容

Usage:
    python scripts/build_section_tree.py <text_md> <toc_json> [--output output.json]
"""
import json
import re
import sys
from pathlib import Path


def parse_pages(content: str) -> dict[int, str]:
    """解析全文，返回 {page_num: content}"""
    pages = re.split(r'<!-- PAGE: (\d+) -->', content)

    page_dict = {}
    for i in range(1, len(pages), 2):
        page_num = int(pages[i])
        page_content = pages[i + 1] if i + 1 < len(pages) else ""
        page_dict[page_num] = page_content.strip()

    return page_dict


def estimate_tokens(text: str) -> int:
    """估算 token 数（英文约 4 字符/token，中文约 2 字符/token）"""
    if not text:
        return 0
    # 简单估算：字符数 / 4
    return max(1, len(text) // 4)


def build_section_tree(toc_data: dict, page_dict: dict[int, str]) -> dict:
    """构建章节树"""
    sections = toc_data.get("sections", [])

    if not sections:
        return {"sections": [], "error": "No sections in TOC"}

    # 构建章节范围
    section_ranges = []
    for i, section in enumerate(sections):
        page = section.get("page")

        # 确定结束页：下一个同级别或更高级别章节的页码 - 1
        # 或者文档最后一页
        next_page = None
        for j in range(i + 1, len(sections)):
            next_section = sections[j]
            next_level = next_section.get("level", 2)
            current_level = section.get("level", 2)

            # 同级别或更高级别的章节才是边界
            if next_level <= current_level and next_section.get("page"):
                next_page = next_section.get("page")
                break

        section_ranges.append({
            "title": section.get("title"),
            "level": section.get("level"),
            "page_start": page,
            "page_end": next_page - 1 if next_page else None,
        })

    # 填充最后一个章节的结束页
    max_page = max(page_dict.keys())
    for i in range(len(section_ranges) - 1, -1, -1):
        if section_ranges[i]["page_end"] is None:
            section_ranges[i]["page_end"] = max_page
        else:
            break

    # 提取内容
    result_sections = []
    current_level1 = None
    level1_children = []

    for sr in section_ranges:
        # 提取页面内容
        content_parts = []
        page_start = sr["page_start"]
        page_end = sr["page_end"]

        if page_start is not None:
            for p in range(page_start, page_end + 1):
                if p in page_dict:
                    content_parts.append(page_dict[p])

        content = "\n\n".join(content_parts)

        section_item = {
            "title": sr["title"],
            "level": sr["level"],
            "page_start": page_start,
            "page_end": page_end,
            "tokens": estimate_tokens(content),
            "content_preview": content[:500] + "..." if len(content) > 500 else content
        }

        if sr["level"] == 1:
            # 保存之前的 level1
            if current_level1 is not None:
                current_level1["children"] = level1_children
                result_sections.append(current_level1)

            current_level1 = section_item
            level1_children = []
        else:
            # level 2 作为 level 1 的子节点
            # 完整内容存在 level 2
            section_item["content"] = content
            level1_children.append(section_item)

    # 保存最后一个 level1
    if current_level1 is not None:
        current_level1["children"] = level1_children
        result_sections.append(current_level1)

    # 计算 level 1 的 tokens
    for s in result_sections:
        s["tokens"] = sum(child.get("tokens", 0) for child in s.get("children", []))
        s["page_start"] = min(
            child["page_start"] for child in s.get("children", []) if child.get("page_start") is not None
        ) if s.get("children") else None
        s["page_end"] = max(
            child["page_end"] for child in s.get("children", []) if child.get("page_end") is not None
        ) if s.get("children") else None

    return {
        "document": {
            "total_pages": max_page,
            "total_sections": len(result_sections),
            "total_subsections": sum(len(s.get("children", [])) for s in result_sections)
        },
        "sections": result_sections
    }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    text_path = sys.argv[1]
    toc_path = sys.argv[2]
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    # 读取全文
    print(f"Reading text: {text_path}")
    with open(text_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 解析页面
    print("Parsing pages...")
    page_dict = parse_pages(content)
    print(f"Total pages: {len(page_dict)}")

    # 读取 TOC
    print(f"Reading TOC: {toc_path}")
    with open(toc_path, "r", encoding="utf-8") as f:
        toc_data = json.load(f)

    # 构建章节树
    print("Building section tree...")
    result = build_section_tree(toc_data, page_dict)

    # 输出摘要
    print(f"\n=== Section Tree Summary ===")
    print(f"Total level-1 sections: {result['document']['total_sections']}")
    print(f"Total level-2 subsections: {result['document']['total_subsections']}")

    for s in result["sections"]:
        print(f"\n[{s['title']}]")
        print(f"  Pages: {s['page_start']} - {s['page_end']}")
        print(f"  Tokens: ~{s['tokens']}")
        print(f"  Children: {len(s.get('children', []))}")
        for child in s.get("children", [])[:3]:
            print(f"    - {child['title']} (p.{child['page_start']}-{child['page_end']}, ~{child['tokens']} tokens)")
        if len(s.get("children", [])) > 3:
            print(f"    ... and {len(s['children']) - 3} more")

    # 保存
    if not output_path:
        output_path = Path(text_path).parent / "section_tree.json"

    print(f"\nSaving to: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
