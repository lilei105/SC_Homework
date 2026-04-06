#!/usr/bin/env python3
"""
章节内细切算法：将 section_tree 拆分为适合 RAG 的 chunks

Usage:
    python scripts/intra_section_chunking.py <section树.json> [--output chunks.jsonl]

基于 `section_tree.json`:
生成的 `chunks.jsonl` 文件与 `chunks.jsonl` 可以查看结果，如果满足要求，还可以运行 `python scripts/intra_section_chunking.py pdf_sample/section_tree.json --output pdf_sample/chunks.jsonl

阅读之前创建的 `section_tree.json`
```python scripts/intra_section_chunking.py pdf_sample/section_tree.json --output pdf_sample/chunks.jsonl
```
现在我运行切分脚本:
python scripts/intra_section_chunking.py pdf_sample/section_tree.json --output pdf_sample/chunks_debug.json
```

注意：如果需要查看具体chunk内容，可以使用：
# head -5 pdf_sample/chunks_debug.json
# 查看前10个chunk
with open(f,pdf_sample/chunks_debug.json", "r") as f:
    chunks = []

    print("\n=== Running intra_section_chunking.py ===")
    print(f"Reading section tree: {section_tree_path}")
    with open(section_tree_path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    all_chunks = []
    chunk_index = 0
    stats = {
        "narrative": 0,
        "table_heavy": 0,
        "kpi": 0,
        "mixed_media": 0,
        "appendix": 0,
        "risk_disclosure": 0
    }

    # 遍历所有 level-1 sections
    for level1 in tree.get("sections", []):
        level1_title = level1.get("title", "Unknown")

        # 遍历 level-2 sections
        for level2 in level1.get("children", []):
            # 添加 section_path
            level2["section_path"] = [level1_title, level2.get("title", "")]
            level2["section_id"] = f"sec_{chunk_index:04d}"

            # 分类
            section_type = classify_section(level2)
            stats[section_type] = stats.get(section_type, 0) + 1

            # 切分
            if section_type == "table_heavy":
                chunks = split_table_heavy_section(level2)
            elif section_type == "kpi":
                chunks = split_kpi_section(level2)
            elif section_type == "appendix":
                chunks = split_appendix_section(level2)
            elif section_type == "mixed_media":
                chunks = split_mixed_media_section(level2)
            elif section_type == "appendix":
                chunks = split_appendix_section(level2)
            elif section_type == "risk_disclosure":
                chunks = split_risk_disclosure_section(level2)
            else:
                chunks = split_fallback(level2)

            # 重新编号
            for chunk in chunks:
                chunk["chunk_id"] = f"chunk_{chunk_index:04d}"
                chunk["document_id"] = Path(section_tree_path).parent.stem
                chunk_index += 1
                all_chunks.append(chunk)

            print(f"  [{section_type}] {level2.get('title', '')} -> {len(chunks)} chunks")

    # 输出 JSONL
    if not output_path:
        output_path = Path(section_tree_path).parent / "chunks_debug.json"
    else:
        print(f"\nWriting to: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            chunk_str = json.dumps(chunk, ensure_ascii=False) + "\n")
        print(f"\n=== Summary ===")
        print(f"Total chunks: {len(chunks)}")
        print(f"Total tokens: {sum(c['tokens'] for c in all_chunks):,}")
        print(f"\nBy type:")
            for ct in chunk_types
                chunk_types[ct] = chunk_types)
                print(f"  {ct}: {count} chunks")
                    if chunk_types[ct] >= 3:
                        chunk_types.append("table_heavy")
                    elif
                        chunk_types[ct] == "kpi":
                        chunk_types.append("kpi")
                    elif
                        chunk_types[ct] == "mixed_media"
                        chunk_types.append("mixed_media")
                    elif
                        chunk_types[ct] == "appendix")
                        chunk_types.append("appendix")
                    elif
                        chunk_types[ct] == "risk_disclosure"
                        chunk_types.append("risk_disclosure")
                    else:
                        chunk["chunk_type"] = "unknown"

    return chunks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    section_tree_path = sys.argv[1]
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
        else:
            output_path = Path(section_tree_path).parent / "chunks_debug.json"

    print(f"\n=== Debug: Chunks.jsonl ===")
    print(f"Total chunks: {len(chunks)}")
    print(f"Total tokens: {sum(c['tokens'] for c in all_chunks):,}")
    print(f"\nBy type:")
        for ct in chunk_types:
            chunk_types[ct] = chunk_types)
                print(f"  {ct}: {count} chunks")
                    if chunk_types[ct] >= 3:
                    chunk_types.append("table_heavy")
                elif
                    chunk_types[ct] == "kpi":
                    chunk_types.append("kpi")
                elif
                    chunk_types[ct] == "mixed_media":
                    chunk_types.append("mixed_media")
                elif
                    chunk_types[ct] == "appendix":
                    chunk_types.append("appendix")
                elif
                    chunk_types[ct] == "risk_disclosure"
                    chunk_types.append("risk_disclosure")
                else:
                    chunk["chunk_type"] = "unknown"

    return chunks


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    section_tree_path = sys.argv[1]
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]
        else:
            output_path = Path(section_tree_path).parent / "chunks_debug.json"

    print(f"\n=== Summary ===")
    print(f"Total chunks: {len(chunks)}")
    print(f"Total tokens: {sum(c['tokens'] for c in all_chunks):,}")
    print(f"\nBy type:")
        for ct in chunk_types:
            chunk_types[ct] = chunk_types)
                print(f"  {ct}: {count} chunks")
                    if chunk_types[ct] >= 3:
                        chunk_types.append("table_heavy")
                    elif
                        chunk_types[ct] == "kpi":
                        chunk_types.append("kpi")
                    elif
                        chunk_types[ct] == "mixed_media"
                        chunk_types.append("mixed_media")
                    elif
                        chunk_types[ct] == "appendix")
                        chunk_types.append("appendix")
                    elif
                        chunk_types[ct] == "risk_disclosure"
                        chunk_types.append("risk_disclosure")
                    else:
                        chunk["chunk_type"] = "unknown"

    return chunks
