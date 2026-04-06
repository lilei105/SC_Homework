#!/usr/bin/env python3
"""
简化 PaddleOCR JSON 输出

只保留核心信息：
- page_index
- blocks: [{ order, label, content }]

Usage:
    python scripts/simplify_paddleocr.py <input_json> <output_json>
"""
import json
import sys
from pathlib import Path


# 需要忽略的 block_label 类型
IGNORE_LABELS = {"header_image", "footer", "footer_image", "header", "aside_text", "vision_footnote"}


def simplify_paddleocr(input_path: str, output_path: str) -> dict:
    """
    简化 PaddleOCR JSON
    """
    print(f"Reading: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total pages: {len(data)}")

    simplified = []

    for page_idx, page in enumerate(data, start=1):
        pruned_result = page.get("prunedResult", {})
        parsing_res_list = pruned_result.get("parsing_res_list", [])

        blocks = []
        for block in parsing_res_list:
            label = block.get("block_label", "")
            content = block.get("block_content", "")
            order = block.get("block_order")

            # 跳过忽略的类型
            if label in IGNORE_LABELS:
                continue

            # 清理内容
            if content:
                content = content.strip()

            blocks.append({
                "order": order,
                "label": label,
                "content": content
            })

        # 按 order 排序
        blocks.sort(key=lambda x: x["order"] if x["order"] is not None else 0)

        simplified.append({
            "page_index": page_idx,
            "blocks": blocks
        })

    # 统计
    total_blocks = sum(len(p["blocks"]) for p in simplified)
    label_counts = {}
    for page in simplified:
        for block in page["blocks"]:
            label = block["label"]
            label_counts[label] = label_counts.get(label, 0) + 1

    print(f"Total blocks: {total_blocks}")
    print(f"Block types:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label}: {count}")

    # 写入
    print(f"Writing: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(simplified, f, indent=2, ensure_ascii=False)

    # 文件大小对比
    input_size = Path(input_path).stat().st_size
    output_size = Path(output_path).stat().st_size
    ratio = output_size / input_size * 100

    print(f"\nFile size:")
    print(f"  Input:  {input_size / 1024 / 1024:.2f} MB")
    print(f"  Output: {output_size / 1024 / 1024:.2f} MB")
    print(f"  Ratio:  {ratio:.1f}%")

    return simplified


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    simplify_paddleocr(input_path, output_path)


if __name__ == "__main__":
    main()
