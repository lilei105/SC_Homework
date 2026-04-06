#!/usr/bin/env python3
"""
从 PaddleOCR JSON 提取纯文本 markdown，带分页符

Usage:
    python scripts/extract_text_from_paddleocr.py <input_json> <output_md>
"""
import json
import sys
from pathlib import Path


# 需要忽略的 block_label 类型
IGNORE_LABELS = {"header_image", "footer", "footer_image", "header", "aside_text", "vision_footnote", "number"}

# 分页符格式
PAGE_MARKER = "<!-- PAGE: {page_num} -->"


def extract_text(input_path: str, output_path: str) -> None:
    """提取纯文本 markdown"""
    print(f"Reading: {input_path}")

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total pages: {len(data)}")

    output_lines = []
    stats = {
        "total_blocks": 0,
        "kept_blocks": 0,
        "ignored_blocks": 0,
        "label_counts": {}
    }

    for page_idx, page in enumerate(data, start=1):
        pruned_result = page.get("prunedResult", {})
        parsing_res_list = pruned_result.get("parsing_res_list", [])

        # 获取图片 URL 映射
        markdown = page.get("markdown", {})
        image_urls = markdown.get("images", {})

        # 添加分页符
        output_lines.append(PAGE_MARKER.format(page_num=page_idx))
        output_lines.append("")

        # 按 block_order 排序
        blocks = sorted(
            parsing_res_list,
            key=lambda x: x.get("block_order", 0) or 0
        )

        page_has_content = False

        for block in blocks:
            stats["total_blocks"] += 1
            label = block.get("block_label", "")
            content = block.get("block_content", "")

            # 统计 label 分布
            stats["label_counts"][label] = stats["label_counts"].get(label, 0) + 1

            # 跳过忽略的类型
            if label in IGNORE_LABELS:
                stats["ignored_blocks"] += 1
                continue

            # 跳过空内容
            if not content or not content.strip():
                continue

            stats["kept_blocks"] += 1
            page_has_content = True

            # 清理内容
            content = content.strip()

            # 替换图片相对路径为完整 URL
            for rel_path, full_url in image_urls.items():
                content = content.replace(rel_path, full_url)

            output_lines.append(content)
            output_lines.append("")

        # 如果整页没有内容，也保留分页符（表示空白页）

    # 写入
    print(f"Writing: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))

    # 统计
    print(f"\nStatistics:")
    print(f"  Total blocks: {stats['total_blocks']}")
    print(f"  Kept blocks: {stats['kept_blocks']}")
    print(f"  Ignored blocks: {stats['ignored_blocks']}")
    print(f"\nBlock type distribution:")
    for label, count in sorted(stats["label_counts"].items(), key=lambda x: -x[1]):
        ignored = " (ignored)" if label in IGNORE_LABELS else ""
        print(f"  {label}: {count}{ignored}")

    # 文件大小
    input_size = Path(input_path).stat().st_size
    output_size = Path(output_path).stat().st_size
    print(f"\nFile size:")
    print(f"  Input:  {input_size / 1024 / 1024:.2f} MB")
    print(f"  Output: {output_size / 1024 / 1024:.2f} MB")
    print(f"  Ratio:  {output_size / input_size * 100:.1f}%")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    extract_text(input_path, output_path)


if __name__ == "__main__":
    main()
