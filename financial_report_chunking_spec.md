# Financial Report → RAG Schema Conversion Implementation Specification (Hybrid: Deterministic + LLM)

This specification describes how to convert PaddleOCR-VL output JSON into structured chunks conforming to financial_report_rag_schema.jsonc.

This is an upgraded version:

Hybrid pipeline = Rule-based algorithms + LLM semantic enhancement

Design goals:

- Ensure structural stability
- Improve chunk semantic quality
- Enhance KPI extraction capability
- Control token costs
- Support batch processing for large files

---

# 1. Input

OCR JSON:

StandardChartered_2025_Annual_Report.pdf_by_PaddleOCR-VL-1.5_mini.json

Per-page structure:

```
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
```

---

# 2. Output

financial_report_rag.json

Structure:

```
{
  document
  sections[]
  chunks[]
}
```

---

# 3. Pipeline Overview

Stage 1 Preprocessing (deterministic)

page → cleaned markdown → token estimate

Stage 2 Page Complexity Assessment (deterministic)

simple page → do not call LLM
complex page → call LLM

Stage 3 LLM Semantic Enhancement (optional)

LLM tasks:

1. Page classification
2. Semantic rewrite
3. Intelligent chunk split
4. KPI extraction
5. Keywords generation
6. Brief generation

Stage 4 Schema Construction (deterministic)

Generate final chunks

---

# 4. Page Complexity Assessment

Decides whether to call LLM.

Complex page conditions:

Satisfies any of:

Large number of numbers:

count(numbers) > 20

Contains image block:

block_label == image

Dense short text:

average line length < 40 characters

Contains % or bps:

>5 occurrences

Contains keywords:

performance
highlights
summary
KPIs
metrics
financial

Implementation:

```python
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
```

---

# 5. Markdown Preprocessing

Remove image tags

![](img.png) → [figure]

Normalize whitespace

---

# 6. LLM Input Structure

LLM input JSON:

```
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
```

Only provide:

Non-header/footer blocks

---

# 7. LLM Output Structure

LLM must return JSON:

```
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
```

---

# 8. financial_metrics Schema

```
{
  metric_name
  value
  unit
  period_label
  context
}
```

Example:

```
{
  metric_name: Return on tangible equity
  value: 14.7
  unit: %
  period_label: FY2025
}
```

---

# 9. Simple Page Chunking

Do not call LLM.

Steps:

Split by heading

If exceeds 500 tokens, split again

Generate chunk

---

# 10. Intelligent Split Strategy

LLM decides:

Whether to split

Split boundaries

Chunk title

---

# 11. chunk_type Mapping

LLM chunk_type → schema chunk_type

narrative → text

table_like → table

kpi_dashboard → table

figure_page → figure

mixed → mixed

---

# 12. Token Control

Hard limit:

500 tokens

If exceeded, must split again:

sliding window

---

# 13. Deterministic Fallback

If LLM fails:

Use simple chunking

Record:

flags.llm_failed = true

---

# 14. source_trace Construction

source_block_ids

From:

LLM

or

Full page block ids

---

# 15. chunk_id

c_p0004_01

---

# 16. bundle_id

bundle_p0004

---

# 17. Section Construction

Priority:

LLM chunk_title

Otherwise:

markdown heading

---

# 18. Main Flow Pseudocode

```python
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
```

---

# 19. Prompt Constraints

System prompt:

You convert OCR text into semantic chunks for financial retrieval.

Rules:

Preserve factual values

Do not hallucinate numbers

Keep units

Keep period labels

Prefer short sentences

Output JSON only

---

# 20. Performance Recommendations

Only call LLM for 20–40% of pages.

Priority:

performance summary pages

financial highlights pages

KPI dashboards

---

# 21. Parallel Processing

Each page is independent.

Can call LLM in parallel.

---

# 22. Cost Control Strategy

max tokens per page prompt: 1200

Only pass necessary blocks

Do not pass bbox

---

# 23. CLI

```
python convert.py
--input ocr.json
--output rag.json
--llm openai
--model gpt-4.1-mini
--parallel 8
```

---

# 24. Acceptance Criteria

chunk token <= 500

At least 1 chunk per page

financial_metrics correct

keywords exist

brief exists

source_trace exists

chunk_type correct

JSON schema valid
