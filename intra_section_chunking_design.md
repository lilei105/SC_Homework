# Intra-Section Auto Chunking Algorithm Design

## 1. Document Purpose

This document defines an **engineerable intra-section auto chunking** solution for further splitting an already-built financial report section tree into high-quality chunks suitable for RAG.

Applicable input:

- Existing full document section tree
- Each section at minimum contains:
  - `title`
  - `level`
  - `page_start`
  - `page_end`
  - `tokens`
  - `content`
  - `children`
- Content sourced from full-text markdown or page/block structure after OCR / layout parsing
- Document may contain:
  - Narrative body text
  - KPI cards
  - Tables
  - Charts
  - Images
  - Infographics
  - Footnotes
  - TOC page remnants
  - Cross-page stitching errors

This document outputs:

1. Algorithm design specification
2. Pseudocode
3. Chunk schema
4. Recommended parameters
5. Implementation notes

---

## 2. Design Goals

### 2.1 Goals

The algorithm must simultaneously satisfy:

1. **Preserve Semantic Integrity**
   - Each chunk should ideally carry one complete topic, one complete metric unit, one complete table unit, or one complete diagram explanation unit.

2. **Suitable for Financial Q&A**
   - Support:
     - Management narrative Q&A
     - Metric value Q&A
     - Metric definition / APM / reconciliation Q&A
     - Table Q&A
     - Chart trend Q&A
     - Sustainability / risk / governance topic Q&A

3. **Support Multimodality**
   - Model text and visual content in parallel, rather than mixing all `<img>` into regular body text chunks.

4. **Support Hierarchical Retrieval**
   - Preserve relationships between section / subsection / block / chunk.

5. **Debuggable**
   - Ability to output intermediate results for manual boundary verification.

### 2.2 Non-Goals

This algorithm is not responsible for:

- OCR itself
- Table OCR low-level implementation
- VLM specific model selection
- Vector database / BM25 / reranker specific implementation

These capabilities only serve as downstream consumers.

---

## 3. Overall Approach

Adopt a **four-stage divide-and-conquer strategy**:

1. **Section Boundary Correction**
   - Based on section title, body heading, intra-page block boundaries, correct potential boundary drift in the section tree.

2. **Section Type Classification**
   - Tag each section to determine which splitter to use.

3. **Candidate Boundary Detection and Scoring**
   - Identify all possible split points within a section, and score each boundary.

4. **Execute Fine Chunking by Type**
   - narrative, KPI, table-heavy, mixed-media, appendix each use different chunking logic.

---

## 4. Input Data Requirements

Recommended input structure:

```json
{
  "document_id": "standard_chartered_annual_report_2025",
  "sections": [
    {
      "section_id": "sec_0001",
      "title": "Group Chief Executive's statement",
      "level": 2,
      "page_start": 6,
      "page_end": 8,
      "tokens": 3584,
      "content": "...",
      "children": []
    }
  ]
}
```

If possible, recommend additionally providing page/block level input:

```json
{
  "pages": [
    {
      "page_no": 6,
      "blocks": [
        {
          "block_id": "p6_b1",
          "type": "heading",
          "text": "Group Chief Executive's statement",
          "bbox": [0, 0, 100, 20]
        },
        {
          "block_id": "p6_b2",
          "type": "paragraph",
          "text": "Our performance in recent years has been strong...",
          "bbox": [0, 30, 100, 80]
        }
      ]
    }
  ]
}
```

### 4.1 Block Type Recommended Enumeration

```text
heading
subheading
paragraph
bullet_list
numbered_list
table
table_row
chart
image
kpi_card
caption
footnote
page_marker
unknown
```

---

## 5. Stage 1: Section Boundary Correction

### 5.1 Problem Background

OCR stitching and TOC-based section tree construction often have these issues:

- Section A's tail falls into section B
- Section B's beginning still carries section A's content
- Title at page start, but body continues from previous page
- One page contains content from two sections simultaneously

Therefore, before intra-section chunking, must first perform **boundary correction**.

### 5.2 Method

For each section:

1. Find best matching heading within `page_start ± window` pages based on `section.title`
2. After finding title anchor, determine actual content start for that section
3. Section's actual end is "before next section's start"
4. If one page contains both sections, cut at block / paragraph level

### 5.3 Title Matching Rules

Title matching must support fuzzy matching:

- Case normalization
- Full-width/half-width normalization
- `'` and `’` normalization
- Remove page numbers, numbering, decorative characters
- OCR spelling error tolerance
- Token overlap / Jaccard / edit distance composite scoring

### 5.4 Boundary Correction Output

After correction, each section outputs:

```json
{
  "section_id": "sec_0003",
  "title": "Group Chief Executive's statement",
  "toc_page_start": 6,
  "resolved_page_start": 6,
  "resolved_block_start": "p6_b1",
  "resolved_page_end": 8,
  "alignment_confidence": 0.97
}
```

---

## 6. Stage 2: Section Type Classification

### 6.1 Why Classification is Needed

Different section types have different optimal splitting methods:

- Narrative long text suits heading-priority splitting
- KPI summary suits metric-level splitting
- Financial tables suit table parent-child splitting
- Mixed text-image suits text/visual parallel splitting
- Appendix and notes suit recursive divide-and-conquer

So before fine chunking, first classify each section.

### 6.2 section_type Enumeration

```text
narrative
kpi
table_heavy
mixed_media
appendix
risk_disclosure
unknown
```

### 6.3 Classification Features

Can use these features for rule-based or lightweight model classification:

- Token count
- Heading density
- `<img>` count
- Table count
- Number density
- Bullet density
- List density
- Average paragraph length
- Whether contains many APM / reconciliation / note / risk terms

### 6.4 Recommended Rules

```python
if table_count >= 3 or numeric_density > 0.35:
    section_type = "table_heavy"
elif kpi_card_count >= 3:
    section_type = "kpi"
elif image_count >= 3 and paragraph_count > 0:
    section_type = "mixed_media"
elif token_count > 6000 and heading_density < threshold:
    section_type = "appendix"
elif contains_risk_keywords:
    section_type = "risk_disclosure"
else:
    section_type = "narrative"
```

---

## 7. Stage 3: Candidate Boundary Detection and Scoring

### 7.1 Core Idea

Don't directly "split left-to-right by length", but first find all possible split points, then score them.

Candidate split point sources:

1. Explicit headings
2. Content type changes
3. Semantic shifts
4. Page transitions
5. Number density changes
6. Table / chart / image boundaries
7. List start or end

### 7.2 Boundary Score

Define boundary score between block[i] and block[i+1]:

```text
boundary_score =
  w1 * heading_signal
+ w2 * type_change_signal
+ w3 * semantic_shift_signal
+ w4 * page_transition_signal
+ w5 * density_change_signal
+ w6 * numeric_table_signal
+ w7 * caption_attachment_signal
```

### 7.3 Signal Explanations

#### heading_signal
Judge if next block is a heading or subheading.

#### type_change_signal
Judge if block type changed, for example:
- paragraph -> table
- paragraph -> chart
- paragraph -> bullet_list
- chart -> paragraph

#### semantic_shift_signal
Use embedding to judge if adjacent blocks have significant semantic jump.

#### page_transition_signal
When crossing pages, if new page starts with heading, table, chart, add score.

#### density_change_signal
Add score when long paragraphs suddenly become dense short sentences, numbers, lists.

#### numeric_table_signal
Detect if number density, percentages, currency amounts, years significantly increase.

#### caption_attachment_signal
If a caption immediately follows image/table/chart, don't split, reduce score.

### 7.4 Boundary Decision Rules

```text
if boundary_score >= hard_cut_threshold:
    Force cut
elif boundary_score >= soft_cut_threshold and current_chunk_size >= target_min:
    Suggest cut
elif current_chunk_size >= target_max:
    Force cut
else:
    Don't cut
```

---

## 8. Stage 4: Execute Fine Chunking by Type

## 8.1 Narrative Splitter

### Applicable Objects
- Chair statement
- CEO statement
- CFO review
- Sustainability review
- Risk overview
- General governance/culture/market environment overview

### Rules

1. Subheading is primary hard boundary
2. If content under subheading is too long, split by paragraph
3. If still too long, split by semantic shift
4. If a subsection is too short, can merge with adjacent same-level subsection

### Recommended Chunk Size
- target: 500 ~ 900 tokens
- min: 250 tokens
- max: 1200 tokens

### Narrative Splitter Output
- text chunk
- linked_visual_chunk_ids (if any)

---

## 8.2 KPI Splitter

### Applicable Objects
- performance highlights
- KPI summary
- operating metrics
- capital ratios
- non-financial KPIs

### Rules

1. Entire KPI area generates one parent chunk
2. Each metric generates one child chunk
3. If a metric has multiple bases (reported / underlying), split into finer child chunks
4. Numbers, units, year-over-year changes, definitions parsed into fields

### Example

```text
kpi::rote::underlying
kpi::rote::reported
kpi::cet1
kpi::mobilising_sustainable_finance
kpi::eps::reported
```

### Recommended Chunk Size
- Child chunk as small as possible
- One metric per chunk

---

## 8.3 Table-Heavy Splitter

### Applicable Objects
- financial summary
- reconciliation
- APM
- notes
- supplementary financial information

### Rules

1. Whole table as one parent chunk
2. Each row/metric as one child chunk
3. Footnote as separate chunk
4. Table header, column names, period fields, currency fields all preserved in metadata
5. If table comes from image, should first structure via table parser / VLM

### Recommended Output

- `table_parent_chunk`
- `table_row_chunk`
- `table_footnote_chunk`

---

## 8.4 Mixed-Media Splitter

### Applicable Objects
- strategy
- business model
- sustainability
- climate
- stakeholder engagement
- Sections with heavy text-image mixing

### Rules

1. Text blocks and visual blocks create separate chunks
2. Visual blocks get separate type identification:
   - chart
   - table
   - diagram
   - photo
   - kpi_card
3. Text chunks preserve `linked_visual_chunk_ids`
4. Visual chunks preserve `linked_text_chunk_ids`

### Visual Block Processing Recommendations

#### chart
Output trends, comparisons, chart title, key observations

#### table image
Output structured rows/columns

#### diagram
Output node relationships, process or framework structure

#### photo
Only weak description, not recommended for main index

#### kpi_card
Output metric name, value, change, definition

---

## 8.5 Appendix / Long Section Splitter

### Applicable Objects
- Long appendix
- notes to financial statements
- risk review
- glossary / supplementary sections

### Rules

Use recursive divide-and-conquer:

1. First split by subheading
2. If sub-block still too long, split by block type
3. If still too long, split by paragraph + semantic break
4. Table branch processed separately, not mixed with narrative

---

## 9. Multimodal Strategy

### 9.1 Principle

Visual content should not be mixed with body text at equal weight in one text chunk, but modeled separately.

### 9.2 visual_role Enumeration

```text
chart
table
diagram
photo
kpi_card
unknown
```

### 9.3 VLM Output Recommended Structure

#### chart

```json
{
  "chart_type": "bar",
  "title_guess": "Operating income by segment",
  "axes": {
    "x": "segment",
    "y": "USD million"
  },
  "series": ["2024", "2025"],
  "key_observations": [
    "CIB remains the largest contributor",
    "WRB grew year-on-year"
  ],
  "numbers_detected": [
    {"label": "CIB", "value": "12394", "unit": "USDm"}
  ],
  "retrieval_text": "This chart compares operating income by segment..."
}
```

#### table image

```json
{
  "title_guess": "Financial summary",
  "columns": ["Metric", "2025", "2024"],
  "rows": [
    ["Operating income", "$20,894m", "$19,7xxm"]
  ],
  "footnotes": [],
  "retrieval_text": "This table lists key financial summary metrics..."
}
```

#### diagram

```json
{
  "title_guess": "Business model",
  "nodes": ["Inputs", "Activities", "Outputs", "Outcomes"],
  "relationships": [
    {"from": "Inputs", "to": "Activities", "label": "enable"}
  ],
  "key_points": ["Cross-border capabilities", "Wealth expertise"],
  "retrieval_text": "This diagram explains the business model..."
}
```

#### kpi_card

```json
{
  "metrics": [
    {
      "name": "RoTE",
      "value": "14.7%",
      "basis": "Underlying",
      "change": "+300bps"
    }
  ],
  "retrieval_text": "KPI card showing RoTE on an underlying basis..."
}
```

---

## 10. Chunk Schema

Recommend using JSONL, one chunk per line.

## 10.1 General Chunk Schema

```json
{
  "chunk_id": "sc_2025_sec003_chunk0007",
  "document_id": "standard_chartered_annual_report_2025",
  "chunk_type": "narrative",
  "section_type": "narrative",
  "title": "Digital transformation and evolving client expectations",
  "page_start": 7,
  "page_end": 8,
  "section_path": [
    "Strategic report",
    "Group Chief Executive's statement",
    "Digital transformation and evolving client expectations"
  ],
  "content": "Money is becoming digital, programmable and increasingly interoperable...",
  "summary": "The CEO explains how digital transformation is reshaping finance...",
  "keywords": [
    "digital transformation",
    "tokenisation",
    "payments",
    "custody"
  ],
  "entities": [
    "Standard Chartered",
    "CIB",
    "WRB"
  ],
  "numbers": [],
  "source_block_ids": ["p7_b4", "p7_b5", "p8_b1"],
  "prev_chunk_id": "sc_2025_sec003_chunk0006",
  "next_chunk_id": "sc_2025_sec003_chunk0008",
  "parent_chunk_id": "sc_2025_sec003_parent",
  "linked_visual_chunk_ids": ["sc_2025_vis_0012"],
  "has_visual_evidence": true,
  "retrieval_hints": {
    "is_definition": false,
    "is_kpi": false,
    "is_table_row": false,
    "is_forward_looking": true,
    "speaker": "Bill Winters"
  }
}
```

---

## 10.2 KPI Chunk Schema

```json
{
  "chunk_id": "sc_2025_kpi_rote_underlying",
  "document_id": "standard_chartered_annual_report_2025",
  "chunk_type": "kpi_metric",
  "section_type": "kpi",
  "title": "Return on tangible equity",
  "page_start": 2,
  "page_end": 3,
  "section_path": [
    "Strategic report",
    "Who we are and what we do",
    "2025 performance highlights"
  ],
  "metric_name": "Return on tangible equity",
  "metric_aliases": ["RoTE"],
  "metric_variant": "Underlying basis",
  "value": "14.7%",
  "unit": "%",
  "change_value": "+300",
  "change_unit": "bps",
  "period": "2025",
  "content": "Return on tangible equity (RoTE), underlying basis, was 14.7%, up 300bps.",
  "source_block_ids": ["p2_b15", "p2_b16"],
  "retrieval_hints": {
    "is_kpi": true,
    "is_financial_metric": true
  }
}
```

---

## 10.3 Table Parent Chunk Schema

```json
{
  "chunk_id": "sc_2025_table_004_parent",
  "document_id": "standard_chartered_annual_report_2025",
  "chunk_type": "table_parent",
  "section_type": "table_heavy",
  "title": "Financial summary",
  "page_start": 54,
  "page_end": 55,
  "section_path": [
    "Financial review",
    "Financial summary"
  ],
  "table_id": "tbl_004",
  "table_title": "Financial summary",
  "columns": ["Metric", "2025", "2024"],
  "content": "Structured representation of the Financial summary table...",
  "row_chunk_ids": [
    "sc_2025_table_004_row_001",
    "sc_2025_table_004_row_002"
  ],
  "footnote_chunk_ids": [
    "sc_2025_table_004_fn_001"
  ]
}
```

---

## 10.4 Table Row Chunk Schema

```json
{
  "chunk_id": "sc_2025_table_004_row_001",
  "document_id": "standard_chartered_annual_report_2025",
  "chunk_type": "table_row",
  "section_type": "table_heavy",
  "page_start": 54,
  "page_end": 54,
  "section_path": [
    "Financial review",
    "Financial summary"
  ],
  "table_id": "tbl_004",
  "row_index": 1,
  "metric_name": "Operating income",
  "row_values": {
    "2025": "$20,894m",
    "2024": "$19,7xxm"
  },
  "unit": "USDm",
  "periods": ["2025", "2024"],
  "content": "Operating income was $20,894m in 2025.",
  "parent_chunk_id": "sc_2025_table_004_parent",
  "retrieval_hints": {
    "is_table_row": true,
    "is_financial_metric": true
  }
}
```

---

## 10.5 Visual Chunk Schema

```json
{
  "chunk_id": "sc_2025_vis_0012",
  "document_id": "standard_chartered_annual_report_2025",
  "chunk_type": "visual_chart",
  "section_type": "mixed_media",
  "visual_role": "chart",
  "page_start": 10,
  "page_end": 10,
  "section_path": [
    "Strategic report",
    "Our business model"
  ],
  "image_id": "p10_img_02",
  "title": "Operating income by segment",
  "content": "This bar chart compares operating income by segment...",
  "structured_data": {
    "chart_type": "bar",
    "series": ["CIB", "WRB", "Ventures"],
    "numbers_detected": [
      {"label": "CIB", "value": "12394", "unit": "USDm"}
    ]
  },
  "linked_text_chunk_ids": [
    "sc_2025_sec005_chunk0003"
  ],
  "retrieval_hints": {
    "has_visual_evidence": true,
    "is_chart": true
  }
}
```

---

## 11. Intermediate Result Files

Recommend outputting these intermediate files for debugging:

### 11.1 `sections_resolved.json`
Section tree after boundary correction

### 11.2 `section_classification.json`
Classification result for each section

### 11.3 `candidate_boundaries.json`
Each candidate boundary and its score

### 11.4 `visual_blocks.json`
Image / chart / table / infographic parsing results

### 11.5 `chunks.jsonl`
Final chunk output

---

## 12. Pseudocode

## 12.1 Main Flow

```python
def build_chunks(document_tree, pages=None):
    resolved_sections = resolve_section_boundaries(document_tree, pages)
    section_types = classify_sections(resolved_sections, pages)

    all_chunks = []

    for section in resolved_sections:
        section_type = section_types[section["section_id"]]

        blocks = extract_section_blocks(section, pages)

        if section_type == "narrative":
            chunks = split_narrative_section(section, blocks)
        elif section_type == "kpi":
            chunks = split_kpi_section(section, blocks)
        elif section_type == "table_heavy":
            chunks = split_table_heavy_section(section, blocks)
        elif section_type == "mixed_media":
            chunks = split_mixed_media_section(section, blocks)
        elif section_type == "appendix":
            chunks = split_appendix_section(section, blocks)
        elif section_type == "risk_disclosure":
            chunks = split_risk_disclosure_section(section, blocks)
        else:
            chunks = split_fallback(section, blocks)

        all_chunks.extend(chunks)

    all_chunks = link_neighbors(all_chunks)
    all_chunks = attach_parent_child_relations(all_chunks)

    return all_chunks
```

---

## 12.2 Boundary Correction

```python
def resolve_section_boundaries(document_tree, pages, window=1):
    sections = flatten_sections(document_tree)
    resolved = []

    for idx, section in enumerate(sections):
        title = normalize_title(section["title"])
        candidate_pages = range(
            max(1, section["page_start"] - window),
            section["page_start"] + window + 1
        )

        best_match = None
        best_score = 0.0

        for page_no in candidate_pages:
            blocks = pages[page_no]["blocks"]
            for block in blocks:
                if block["type"] in ("heading", "subheading", "paragraph"):
                    score = fuzzy_title_score(title, normalize_title(block.get("text", "")))
                    if score > best_score:
                        best_score = score
                        best_match = (page_no, block["block_id"])

        resolved_section = dict(section)
        resolved_section["resolved_page_start"] = best_match[0] if best_match else section["page_start"]
        resolved_section["resolved_block_start"] = best_match[1] if best_match else None
        resolved_section["alignment_confidence"] = best_score
        resolved.append(resolved_section)

    resolved = resolve_section_end_positions(resolved, pages)
    return resolved
```

---

## 12.3 Section Classification

```python
def classify_sections(sections, pages):
    result = {}

    for section in sections:
        blocks = extract_section_blocks(section, pages)

        features = {
            "token_count": estimate_tokens(blocks),
            "table_count": count_type(blocks, "table"),
            "chart_count": count_type(blocks, "chart"),
            "image_count": count_type(blocks, "image"),
            "kpi_card_count": count_type(blocks, "kpi_card"),
            "bullet_count": count_type(blocks, "bullet_list"),
            "numeric_density": calc_numeric_density(blocks),
            "heading_density": calc_heading_density(blocks),
            "risk_keyword_score": risk_keyword_score(blocks),
        }

        if features["table_count"] >= 3 or features["numeric_density"] > 0.35:
            section_type = "table_heavy"
        elif features["kpi_card_count"] >= 3:
            section_type = "kpi"
        elif (features["chart_count"] + features["image_count"]) >= 3 and features["heading_density"] > 0:
            section_type = "mixed_media"
        elif features["token_count"] > 6000 and features["heading_density"] < 0.02:
            section_type = "appendix"
        elif features["risk_keyword_score"] > 0.6:
            section_type = "risk_disclosure"
        else:
            section_type = "narrative"

        result[section["section_id"]] = section_type

    return result
```

---

## 12.4 Candidate Boundary Detection

```python
def detect_candidate_boundaries(blocks):
    candidates = []

    for i in range(len(blocks) - 1):
        left_block = blocks[i]
        right_block = blocks[i + 1]

        signals = {
            "heading_signal": heading_signal(right_block),
            "type_change_signal": type_change_signal(left_block, right_block),
            "semantic_shift_signal": semantic_shift_signal(left_block, right_block),
            "page_transition_signal": page_transition_signal(left_block, right_block),
            "density_change_signal": density_change_signal(left_block, right_block),
            "numeric_table_signal": numeric_table_signal(left_block, right_block),
            "caption_attachment_signal": caption_attachment_signal(left_block, right_block),
        }

        score = (
            0.30 * signals["heading_signal"] +
            0.20 * signals["type_change_signal"] +
            0.20 * signals["semantic_shift_signal"] +
            0.10 * signals["page_transition_signal"] +
            0.08 * signals["density_change_signal"] +
            0.10 * signals["numeric_table_signal"] -
            0.08 * signals["caption_attachment_signal"]
        )

        candidates.append({
            "index": i,
            "left_block_id": left_block["block_id"],
            "right_block_id": right_block["block_id"],
            "signals": signals,
            "score": score
        })

    return candidates
```

---

## 12.5 Narrative Splitter

```python
def split_narrative_section(section, blocks):
    chunks = []
    grouped = split_by_headings(blocks)

    for group in grouped:
        subgroups = split_if_too_long_by_semantic_break(group, target_max_tokens=1000)

        for subgroup in subgroups:
            subgroup = merge_if_too_short(subgroup, min_tokens=250)
            chunk = build_narrative_chunk(section, subgroup)
            chunks.append(chunk)

    return chunks
```

---

## 12.6 KPI Splitter

```python
def split_kpi_section(section, blocks):
    chunks = []

    parent_chunk = build_kpi_parent_chunk(section, blocks)
    chunks.append(parent_chunk)

    metrics = extract_kpi_records(blocks)

    for metric in metrics:
        child_chunk = build_kpi_metric_chunk(section, metric, parent_chunk["chunk_id"])
        chunks.append(child_chunk)

    return chunks
```

---

## 12.7 Table-Heavy Splitter

```python
def split_table_heavy_section(section, blocks):
    chunks = []

    tables = extract_tables(blocks)

    for table in tables:
        parent_chunk = build_table_parent_chunk(section, table)
        chunks.append(parent_chunk)

        for row in table["rows"]:
            row_chunk = build_table_row_chunk(section, table, row, parent_chunk["chunk_id"])
            chunks.append(row_chunk)

        for footnote in table.get("footnotes", []):
            fn_chunk = build_table_footnote_chunk(section, table, footnote, parent_chunk["chunk_id"])
            chunks.append(fn_chunk)

    residual_blocks = remove_table_blocks(blocks, tables)
    if residual_blocks:
        chunks.extend(split_narrative_section(section, residual_blocks))

    return chunks
```

---

## 12.8 Mixed-Media Splitter

```python
def split_mixed_media_section(section, blocks):
    chunks = []

    text_blocks = []
    visual_items = []

    for block in blocks:
        if block["type"] in ("chart", "image", "table", "kpi_card"):
            visual_items.append(block)
        else:
            text_blocks.append(block)

    text_chunks = split_narrative_section(section, text_blocks)
    chunks.extend(text_chunks)

    visual_chunks = []
    for visual in visual_items:
        visual_role = classify_visual_role(visual)
        visual_structured = parse_visual_block(visual, visual_role)
        vchunk = build_visual_chunk(section, visual, visual_role, visual_structured)
        visual_chunks.append(vchunk)

    chunks.extend(visual_chunks)
    chunks = link_text_and_visual_chunks(chunks, section)

    return chunks
```

---

## 12.9 Appendix Splitter

```python
def split_appendix_section(section, blocks):
    if estimate_tokens(blocks) <= 1500:
        return [build_narrative_chunk(section, blocks)]

    heading_groups = split_by_headings(blocks)
    if len(heading_groups) > 1:
        chunks = []
        for group in heading_groups:
            chunks.extend(split_appendix_group(section, group))
        return chunks

    type_groups = split_by_type_change(blocks)
    if len(type_groups) > 1:
        chunks = []
        for group in type_groups:
            chunks.extend(split_appendix_group(section, group))
        return chunks

    return split_if_too_long_by_semantic_break(blocks, target_max_tokens=1200)
```

---

## 13. Parameter Recommendations

```yaml
chunking:
  narrative:
    target_tokens: 700
    min_tokens: 250
    max_tokens: 1200
    overlap_tokens: 80

  appendix:
    target_tokens: 900
    min_tokens: 300
    max_tokens: 1500
    overlap_tokens: 100

  boundary_scoring:
    hard_cut_threshold: 0.72
    soft_cut_threshold: 0.50

  title_alignment:
    search_window_pages: 1
    min_match_score: 0.72

  table:
    enable_row_level_chunks: true
    enable_footnote_chunks: true

  visual:
    create_visual_chunks: true
    create_photo_chunks: false
    attach_visual_to_nearest_text_chunk: true
```

---

## 14. Implementation Recommendations

### 14.1 Don't Rely Solely on Markdown Text Splitting
When actually chunking, try to base on page/block level structure, not pure strings.

### 14.2 Distinguish TOC Pages and Body Text
TOC pages can be kept as navigation information, but not recommended for main retrieval corpus.

### 14.3 Don't Mix Tables with Narrative
Tables should always be prioritized for structuring.

### 14.4 Process Charts and Images by Role
chart / table image / diagram / photo / kpi_card should not share the same prompt and schema.

### 14.5 Output Intermediate Results for Manual Spot-Check
Strongly recommend outputting intermediate JSON at each stage to quickly locate wrong boundaries, misclassification, too-fragmented or too-coarse issues.

---

## 15. Quality Assessment Recommendations

Recommend at least these spot-checks:

1. **Boundary Accuracy**
   - Does section start still contain previous chapter remnants
   - Is section end contaminated by next chapter

2. **Chunk Granularity**
   - Too fragmented
   - Too long
   - Multiple topics forced into one chunk

3. **Metric Q&A Capability**
   - Can single metric chunk answer questions independently

4. **Table Q&A Capability**
   - Is table row-level chunk sufficient for metric lookup

5. **Chart Supplement Capability**
   - When retrieving body text, can it link to related visual chunks

### Recommended Sample Questions

- What was the 2025 underlying RoTE?
- What did the CEO say about digital transformation?
- What is the bank's strategy in sustainable finance?
- What does the financial summary table say about operating income?
- What does the business model diagram show?

---

## 16. Recommended Implementation Order

Recommend implementing in this order:

1. Section boundary correction
2. Section type classification
3. Narrative splitter
4. KPI splitter
5. Table-heavy splitter
6. Mixed-media splitter
7. Appendix splitter
8. Visual parsing
9. Parent-child / neighbor linkage
10. Quality spot-check script

---

## 17. Final Conclusion

This solution doesn't rely on a single chunking algorithm, but adopts:

**Boundary correction + Section classification + Candidate boundary scoring + Type-specific splitter + Multimodal parallel modeling**

For financial reports - highly structured, high number density, mixed text-image, table-dense large documents - this is a more stable and RAG-suitable approach than fixed token splitting or single semantic splitter.
