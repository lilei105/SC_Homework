# Financial Report → RAG Schema 转换实现规范（Hybrid: Deterministic + LLM）

本规范描述如何将 PaddleOCR-VL 输出 JSON 转换为符合 financial_report_rag_schema.jsonc 的结构化 chunks。

本版本为升级版：

Hybrid pipeline = 规则算法 + LLM 语义增强

设计目标：

- 保证结构稳定
- 提升 chunk 语义质量
- 提升 KPI 抽取能力
- 控制 token 成本
- 可分批处理大文件

---

# 1. 输入

OCR JSON：

StandardChartered_2025_Annual_Report.pdf_by_PaddleOCR-VL-1.5_mini.json

每页结构：

{
  prunedResult:
  {
    page_index
    page_parsing_result:
    {
      markdown.text
      parsing_res_list[]
    }
  }
}

---

# 2. 输出

financial_report_rag.json

结构：

{
  document
  sections[]
  chunks[]
}

---

# 3. pipeline 总览

Stage 1 预处理（deterministic）

page → cleaned markdown → token estimate

Stage 2 页面复杂度判断（deterministic）

simple page → 不调用 LLM
complex page → 调用 LLM

Stage 3 LLM semantic enhancement（optional）

LLM tasks:

1 页面分类
2 semantic rewrite
3 intelligent chunk split
4 KPI extraction
5 keywords generation
6 brief generation

Stage 4 schema 构造（deterministic）

生成最终 chunks

---

# 4. 页面复杂度判断

决定是否调用 LLM。

complex page 条件：

满足任一：

大量数字：

count(numbers) > 20

存在 image block：

block_label == image

短文本密集：

平均行长度 < 40 字符

存在 % 或 bps：

>5 occurrences

包含关键词：

performance
highlights
summary
KPIs
metrics
financial

实现：


def is_complex_page(md_text, blocks):

    num_numbers = count_numbers(md_text)

    num_percent = md_text.count('%')

    has_image = any(b['block_label']=='image' for b in blocks)

    avg_line_length = average_line_length(md_text)

    if num_numbers > 20:
        return True

    if num_percent > 5:
        return True

    if has_image:
        return True

    if avg_line_length < 40:
        return True

    return False

---

# 5. markdown 预处理

remove image tags

![](img.png) → [figure]

normalize whitespace

---

# 6. LLM 输入结构

LLM 输入 JSON：

{
  page_index
  markdown
  blocks:
  [
    {
      block_id
      label
      text
    }
  ]
  section_hint
}

只提供：

非 header/footer blocks

---

# 7. LLM 输出结构

LLM 必须返回 JSON：

{
  page_type:

  narrative
  kpi_dashboard
  table_like
  figure_page
  mixed

  should_split:
  boolean

  chunks:
  [
    {
      chunk_title
      content
      source_block_ids[]
      chunk_type

      financial_metrics[]

      keywords[]

      brief
    }
  ]
}

---

# 8. financial_metrics schema

{
  metric_name
  value
  unit
  period_label
  context
}

示例：

{
  metric_name: Return on tangible equity
  value: 14.7
  unit: %
  period_label: FY2025
}

---

# 9. simple page chunking

不调用 LLM。

步骤：

按 heading 切分

超过 500 tokens 再切

生成 chunk

---

# 10. intelligent split strategy

LLM 决定：

是否拆分

拆分边界

chunk title

---

# 11. chunk_type 映射

LLM chunk_type → schema chunk_type

narrative → text

table_like → table

kpi_dashboard → table

figure_page → figure

mixed → mixed

---

# 12. token 控制

硬限制：

500 tokens

超过必须再次切分：

sliding window

---

# 13. deterministic fallback

若 LLM 失败：

使用 simple chunking

记录：

flags.llm_failed = true

---

# 14. source_trace 构造

source_block_ids

来自：

LLM

或

整页 block ids

---

# 15. chunk_id

c_p0004_01

---

# 16. bundle_id

bundle_p0004

---

# 17. section 构造

优先使用：

LLM chunk_title

否则：

markdown heading

---

# 18. 主流程伪代码

for page in document:

    md = clean_markdown(page.markdown)

    blocks = filter_blocks(page.blocks)

    if is_complex_page(md, blocks):

        llm_result = call_llm()

        chunks = build_chunks_from_llm(llm_result)

    else:

        chunks = simple_split(md)

    enforce_token_limit(chunks)

    attach_source_trace(chunks)

---

# 19. prompt 约束

system prompt：

You convert OCR text into semantic chunks for financial retrieval.

Rules:

Preserve factual values

Do not hallucinate numbers

Keep units

Keep period labels

Prefer short sentences

Output JSON only

---

# 20. 性能建议

只对 20–40% 页面调用 LLM。

优先调用：

performance summary pages

financial highlights pages

KPI dashboards

---

# 21. 并行处理

每页独立。

可并行调用 LLM。

---

# 22. 成本控制策略

max tokens per page prompt: 1200

只传必要 blocks

不传 bbox

---

# 23. CLI

python convert.py

--input ocr.json

--output rag.json

--llm openai

--model gpt-4.1-mini

--parallel 8

---

# 24. 验收标准

chunk token <= 500

每页 ≥1 chunk

financial_metrics 正确

keywords 存在

brief 存在

source_trace 存在

chunk_type 正确

JSON schema valid

