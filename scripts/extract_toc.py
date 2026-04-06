#!/usr/bin/env python3
"""
从提取的 markdown 文件中提取目录结构（使用 LLM）

Usage:
    python scripts/extract_toc.py <input_md> [--output output.json]
"""
import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI


def extract_first_n_pages(content: str, n: int = 5) -> str:
    """提取前 N 页内容"""
    # 按 PAGE 分割
    parts = re.split(r'<!-- PAGE: (\d+) -->', content)

    result_parts = []
    for i in range(1, min(len(parts), 2 * n + 1), 2):
        page_num = parts[i]
        page_content = parts[i + 1] if i + 1 < len(parts) else ""
        result_parts.append(f"<!-- PAGE: {page_num} -->")
        result_parts.append(page_content.strip())

    return "\n\n".join(result_parts)


def extract_toc_with_llm(toc_text: str, api_key: str, base_url: str, model: str) -> dict:
    """使用 LLM 提取目录结构"""
    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )

    system_prompt = """你是一个文档结构提取助手。请从目录文本中提取所有章节及其页码。

输出 JSON 格式：
{
  "sections": [
    {"title": "Strategic report", "level": 1},
    {"title": "Who we are and what we do", "page": 2, "level": 2},
    {"title": "Group Chair's statement", "page": 4, "level": 2}
  ]
}

规则：
- level 1 = 大类章节（通常以 # 或 ## 开头，没有页码）
- level 2 = 具体章节条目（有页码的行）
- page 是整数，如果无法确定则设为 null
- 忽略图片标签、HTML 标签、无关文字
- 只输出 JSON，不要有其他文字"""

    user_prompt = f"""请从以下文本中提取章节结构：

---
{toc_text}
---

请输出 JSON："""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
    )

    result_text = response.choices[0].message.content.strip()

    # 提取 JSON（可能被 ```json 包裹）
    if "```json" in result_text:
        result_text = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL).group(1)
    elif "```" in result_text:
        result_text = re.search(r'```\s*(.*?)\s*```', result_text, re.DOTALL).group(1)

    return json.loads(result_text)


def load_env(env_path: str) -> dict:
    """加载 .env 文件"""
    env_vars = {}
    if Path(env_path).exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = None

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output_path = sys.argv[idx + 1]

    # 加载环境变量
    script_dir = Path(__file__).parent
    env_path = script_dir.parent / "backend" / ".env"
    env_vars = load_env(str(env_path))

    # 优先使用命令行环境变量，其次使用 .env
    api_key = os.environ.get("SILICONFLOW_API_KEY") or env_vars.get("SILICONFLOW_API_KEY")
    base_url = os.environ.get("SILICONFLOW_BASE_URL") or env_vars.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    model = os.environ.get("SILICONFLOW_MODEL") or env_vars.get("SILICONFLOW_MODEL", "Pro/zai-org/GLM-4.7")

    if not api_key or api_key == "YOUR_API_KEY_HERE":
        print("ERROR: SILICONFLOW_API_KEY not set. Please set it in backend/.env or environment variable.")
        sys.exit(1)

    # 读取文件
    print(f"Reading: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 提取前5页
    print("Extracting first 5 pages...")
    first_pages = extract_first_n_pages(content, 5)
    print(f"First 5 pages length: {len(first_pages)} chars")

    # 调用 LLM
    print(f"Calling LLM ({model})...")
    result = extract_toc_with_llm(first_pages, api_key, base_url, model)

    # 输出结果
    sections = result.get("sections", [])
    print(f"\nExtracted {len(sections)} sections:")
    for s in sections[:20]:
        level_mark = "  " if s.get("level") == 2 else ""
        page_str = f"p.{s['page']}" if s.get("page") else ""
        print(f"  {level_mark}{s['title']} {page_str}")
    if len(sections) > 20:
        print(f"  ... and {len(sections) - 20} more")

    # 保存
    if not output_path:
        output_path = Path(input_path).parent / "toc_structure.json"

    print(f"\nSaving to: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
