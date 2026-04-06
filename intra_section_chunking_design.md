# 章节内自动细切算法设计说明

## 1. 文档目的

本文档定义一个可工程化实现的 **章节内自动细切（intra-section auto chunking）** 方案，用于将已经构建好的财报章节树进一步拆分为适合 RAG 的高质量 chunks。

适用输入：

- 已有全文章节树
- 每个 section 至少包含：
  - `title`
  - `level`
  - `page_start`
  - `page_end`
  - `tokens`
  - `content`
  - `children`
- 内容来源于 OCR / layout 解析后的全文 markdown 或 page/block 结构
- 文档可能包含：
  - narrative 正文
  - KPI 卡片
  - 表格
  - 图表
  - 图片
  - 信息图
  - 脚注
  - 目录页残留
  - 跨页拼接误差

本文档输出：

1. 算法设计说明
2. 伪代码
3. chunk schema
4. 推荐参数
5. 实现注意事项

---

## 2. 设计目标

### 2.1 目标

该算法需要同时满足以下目标：

1. **保持语义完整**
   - 每个 chunk 尽量承载一个完整主题、一个完整指标单元、一个完整表格单元，或一个完整图示解释单元。

2. **适合财报问答**
   - 支持：
     - 管理层叙述问答
     - 指标数值问答
     - 指标口径 / APM / reconciliation 问答
     - 表格问答
     - 图表趋势问答
     - 可持续 / 风险 /治理类主题问答

3. **支持多模态**
   - 文本与视觉内容并行建模，而不是把所有 `<img>` 混入普通正文 chunk。

4. **支持层级检索**
   - 保留 section / subsection / block / chunk 之间的关系。

5. **可调试**
   - 能够输出中间结果，便于人工检查边界是否正确。

### 2.2 非目标

本算法不负责：

- OCR 本身
- 表格 OCR 的底层实现
- VLM 的具体模型选型
- 向量库 / BM25 / reranker 的具体实现

这些能力只作为下游消费者。

---

## 3. 总体思路

采用 **四阶段分治策略**：

1. **章节边界纠偏**
   - 基于 section 标题、正文 heading、页内 block 边界，修正章节树中可能存在的边界漂移。

2. **章节类型分类**
   - 给每个 section 打标签，决定它使用哪一种 splitter。

3. **候选切点检测与评分**
   - 在 section 内识别所有可能的切分点，并对切点打分。

4. **按类型执行细切**
   - narrative、KPI、table-heavy、mixed-media、appendix 各自使用不同的细切逻辑。

---

## 4. 输入数据要求

推荐输入结构如下：

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

如果可以，推荐额外提供 page/block 级输入：

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

### 4.1 block type 推荐枚举

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

## 5. 第一阶段：章节边界纠偏

### 5.1 问题背景

OCR 拼接和基于 TOC 的章节树构建，常出现以下问题：

- section A 的尾巴落入 section B
- section B 的开头还带着 section A 的内容
- 标题在页首，但正文从上一页延续
- 一页内同时包含两个 section 的内容

因此在做 section 内细切前，必须先做 **边界纠偏**。

### 5.2 方法

对每个 section 执行：

1. 根据 `section.title` 在 `page_start ± window` 页内查找最匹配 heading
2. 找到标题锚点后，确定该 section 的实际内容起点
3. section 的实际终点为“下一 section 的起点之前”
4. 若一页中同时存在前后两个 section，则在 block / paragraph 级别切断

### 5.3 标题匹配规则

标题匹配必须支持模糊匹配：

- 大小写归一
- 全角半角归一
- `'` 与 `’` 归一
- 去除页码、编号、装饰字符
- OCR 拼写误差容忍
- token overlap / Jaccard / edit distance 综合评分

### 5.4 边界纠偏输出

纠偏后，每个 section 输出：

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

## 6. 第二阶段：章节类型分类

### 6.1 为什么需要分类

不同类型 section 的最佳切分方法不同：

- narrative 长文适合标题优先切分
- KPI 汇总适合指标级切分
- 财务表格适合表格父子切分
- 图文混排适合文本/视觉并行切分
- 附录和 notes 适合递归式分治

所以在细切前，先给每个 section 分类。

### 6.2 section_type 枚举

```text
narrative
kpi
table_heavy
mixed_media
appendix
risk_disclosure
unknown
```

### 6.3 分类特征

可使用以下特征做规则分类或轻量模型分类：

- token 数量
- 标题密度
- `<img>` 数量
- 表格数量
- 数字密度
- bullet 密度
- 列表密度
- 平均段落长度
- 是否包含大量 APM / reconciliation / note / risk terms

### 6.4 推荐规则

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

## 7. 第三阶段：候选切点检测与评分

### 7.1 核心思想

不直接“从左到右按长度切”，而是先找到所有可能切点，再给切点打分。

切点候选来源：

1. 显式标题
2. 内容类型变化
3. 语义突变
4. 页面切换
5. 数字密度变化
6. 表格 / 图表 / 图片边界
7. 列表开始或结束

### 7.2 boundary score

定义 block[i] 与 block[i+1] 之间的边界分数：

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

### 7.3 各信号说明

#### heading_signal
判断下一个 block 是否为标题或小标题。

#### type_change_signal
判断 block 类型是否发生变化，例如：
- paragraph -> table
- paragraph -> chart
- paragraph -> bullet_list
- chart -> paragraph

#### semantic_shift_signal
使用 embedding 判断相邻 block 语义是否发生明显跳变。

#### page_transition_signal
跨页时，如果新页页首出现标题、表格、图表，则加分。

#### density_change_signal
当长段落突然变成密集短句、数字、列表时加分。

#### numeric_table_signal
检测数字密度、百分比、货币金额、年份等是否显著增高。

#### caption_attachment_signal
若某个 caption 紧跟 image/table/chart，不切开，反向降分。

### 7.4 切点决策规则

```text
if boundary_score >= hard_cut_threshold:
    强制切
elif boundary_score >= soft_cut_threshold and current_chunk_size >= target_min:
    建议切
elif current_chunk_size >= target_max:
    强制切
else:
    不切
```

---

## 8. 第四阶段：按类型执行细切

## 8.1 narrative splitter

### 适用对象
- Chair statement
- CEO statement
- CFO review
- Sustainability review
- 风险综述
- 普通治理/文化/市场环境综述

### 规则

1. 小标题是一级硬边界
2. 若小标题下过长，再按段落切
3. 若仍过长，再根据语义跳变切
4. 若某个小节过短，可与相邻同级小节合并

### 推荐 chunk 大小
- target: 500 ~ 900 tokens
- min: 250 tokens
- max: 1200 tokens

### narrative splitter 产物
- text chunk
- linked_visual_chunk_ids（如有）

---

## 8.2 KPI splitter

### 适用对象
- performance highlights
- KPI summary
- operating metrics
- capital ratios
- non-financial KPIs

### 规则

1. 整个 KPI 区域生成一个 parent chunk
2. 每个指标生成一个 child chunk
3. 若一个指标有多个 basis（reported / underlying），拆为更细 child chunk
4. 数字、单位、同比变化、口径分别解析为字段

### 例子

```text
kpi::rote::underlying
kpi::rote::reported
kpi::cet1
kpi::mobilising_sustainable_finance
kpi::eps::reported
```

### 推荐 chunk 大小
- child chunk 尽量小
- 每个指标一个 chunk

---

## 8.3 table-heavy splitter

### 适用对象
- financial summary
- reconciliation
- APM
- notes
- supplementary financial information

### 规则

1. 整表一个 parent chunk
2. 每一行/每一指标一个 child chunk
3. footnote 单独 chunk
4. 表头、列名、期间字段、币种字段都保留在 metadata 中
5. 如果表格来自图片，应先通过 table parser / VLM 结构化

### 推荐产物

- `table_parent_chunk`
- `table_row_chunk`
- `table_footnote_chunk`

---

## 8.4 mixed-media splitter

### 适用对象
- strategy
- business model
- sustainability
- climate
- stakeholder engagement
- 含较多图文混排的章节

### 规则

1. 文本块和视觉块分开建 chunk
2. 视觉块单独做类型识别：
   - chart
   - table
   - diagram
   - photo
   - kpi_card
3. 文本 chunk 保留 `linked_visual_chunk_ids`
4. 视觉 chunk 保留 `linked_text_chunk_ids`

### 视觉块处理建议

#### chart
输出趋势、比较、图表标题、关键观察点

#### table image
输出结构化 rows/columns

#### diagram
输出节点关系、流程或框架结构

#### photo
只做弱描述，不建议强入主索引

#### kpi_card
输出指标名称、值、变化、口径

---

## 8.5 appendix / long section splitter

### 适用对象
- 超长附录
- notes to financial statements
- risk review
- glossary / supplementary sections

### 规则

采用递归式分治：

1. 先按子标题切
2. 若子块仍过长，再按 block type 分
3. 若仍过长，再按 paragraph + semantic break 分
4. 表格分支单独处理，不与 narrative 混切

---

## 9. 多模态策略

### 9.1 原则

视觉内容不直接与正文等权混在一个文本 chunk 里，而是单独建模。

### 9.2 visual_role 枚举

```text
chart
table
diagram
photo
kpi_card
unknown
```

### 9.3 VLM 输出推荐结构

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

## 10. chunk schema

推荐使用 JSONL，每个 chunk 一行。

## 10.1 通用 chunk schema

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

## 10.2 KPI chunk schema

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

## 10.3 table parent chunk schema

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

## 10.4 table row chunk schema

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

## 10.5 visual chunk schema

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

## 11. 中间结果文件

推荐输出以下中间文件，方便调试：

### 11.1 `sections_resolved.json`
边界纠偏后的章节树

### 11.2 `section_classification.json`
每个 section 的分类结果

### 11.3 `candidate_boundaries.json`
每个候选切点及其分数

### 11.4 `visual_blocks.json`
图片 / 图表 / 表格 / 信息图解析结果

### 11.5 `chunks.jsonl`
最终 chunk 输出

---

## 12. 伪代码

## 12.1 主流程

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

## 12.2 边界纠偏

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

## 12.3 section 分类

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

## 12.4 候选切点检测

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

## 12.5 narrative splitter

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

## 12.6 KPI splitter

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

## 12.7 table-heavy splitter

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

## 12.8 mixed-media splitter

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

## 12.9 appendix splitter

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

## 13. 参数建议

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

## 14. 实现建议

### 14.1 不要只靠 markdown 文本切分
真正切分时，应尽量基于 page/block 级结构，而不是纯字符串。

### 14.2 目录页和正文要区分
目录页可以保留为导航信息，但不建议进入主检索语料。

### 14.3 表格不要和 narrative 混切
表格应始终优先结构化。

### 14.4 图表和图片分角色处理
chart / table image / diagram / photo / kpi_card 不应共用同一 prompt 和同一 schema。

### 14.5 输出中间结果，便于人工抽检
强烈建议在每个阶段输出中间 JSON，以便快速定位切错边界、误分类、过碎或过粗的问题。

---

## 15. 质量评估建议

建议至少做以下抽检：

1. **边界准确性**
   - section 开头是否仍含前一章残留
   - section 结尾是否被下一章污染

2. **chunk 粒度**
   - 是否过碎
   - 是否过长
   - 是否把多个主题硬塞进一个 chunk

3. **指标问答能力**
   - 单指标 chunk 是否可单独回答问题

4. **表格问答能力**
   - 表格行级 chunk 是否足以支持 metric lookup

5. **图表补充能力**
   - 检索到正文时，是否能关联相关 visual chunk

### 推荐抽样问题

- What was the 2025 underlying RoTE?
- What did the CEO say about digital transformation?
- What is the bank's strategy in sustainable finance?
- What does the financial summary table say about operating income?
- What does the business model diagram show?

---

## 16. 推荐实施顺序

建议按以下顺序实现：

1. section 边界纠偏
2. section 类型分类
3. narrative splitter
4. KPI splitter
5. table-heavy splitter
6. mixed-media splitter
7. appendix splitter
8. visual parsing
9. parent-child / neighbor linkage
10. 质量抽检脚本

---

## 17. 最终结论

本方案不依赖单一 chunking 算法，而是采用：

**边界纠偏 + 章节分类 + 候选切点打分 + 类型专用 splitter + 多模态并行建模**

对于财报这类高结构、强数字密度、图文混排、表格密集的大型文档，这是比固定 token 切分或单一 semantic splitter 更稳、更适合 RAG 的路线。
