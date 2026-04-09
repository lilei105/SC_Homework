# Chunking Pipeline: From OCR to Searchable Chunks

## Overview

The chunking pipeline transforms raw OCR output into semantically coherent, page-accurate chunks ready for vector embedding. It is designed specifically for financial reports — documents with rich structure (tables of contents, sections, subsections, financial tables) where naive splitting would destroy meaning.

```
OCR Output → Page Parsing → TOC Extraction → Section Tree → Table Conversion → Chunking → Page-Tagged Chunks
```

## Pipeline Stages

### Stage 1: Page Parsing

OCR output arrives as a structured JSON with per-page content. Each page is extracted and indexed by page number:

```json
{
  "pages": [
    {"page_num": 0, "markdown": "# Annual Report 2025\n..."},
    {"page_num": 1, "markdown": "## Financial Highlights\n..."}
  ]
}
```

The parser (`chunker.py:parse_pages`) converts this into an internal `page_dict` mapping 1-indexed page numbers to their content:

```python
page_dict = {
    1: "# Annual Report 2025\n...",
    2: "## Financial Highlights\n...",
    ...
}
```

This per-page structure is the foundation for all subsequent page tracking.

### Stage 2: TOC Extraction

The system uses LLM (Qwen Turbo) to detect and extract the table of contents from the first 5 pages. This is done page-by-page — once a TOC page is found, scanning stops.

**Prompt strategy** (`chunker.py:check_page_for_toc`):
- Input: A single page's content
- Output: `{"is_toc": true, "sections": [{"title": "Strategic Report", "page": 2, "level": 1}, ...]}`
- Two-level hierarchy: Level 1 = major sections, Level 2 = subsections with page numbers

For a 481-page annual report, this produces ~58 section entries spanning the entire document.

**Error handling:**
- JSON repair for trailing commas and malformed output
- Retry logic for truncated responses
- Token limit increased to 4096 for large TOCs (learned from a failure on a 481-page document)

### Stage 3: Section Tree Construction

The TOC entries are converted into a hierarchical section tree (`chunker.py:build_section_tree`):

```
Strategic Report (pages 2-50)
├── Who We Are (pages 3-5)
├── CEO Letter (pages 6-8)
├── Financial Highlights (pages 9-20)
└── Risk Report (pages 30-45)
Performance Report (pages 51-120)
├── Income Statement (pages 55-70)
└── Balance Sheet (pages 71-90)
...
```

**Page range resolution**: Each section's page range is computed from TOC entries — a section starts at its TOC page and ends at the page before the next sibling section.

**Content assembly**: For each section, all pages in its range are concatenated with invisible page markers:

```python
content_parts.append(self._inject_page_marker(p, page_dict[p]))
# Result: "\x0056\x00<table>...</table>\n\n\x0057\x00Some text..."
```

These null-byte markers (`\x00`) enable precise page tracking through all subsequent processing.

### Stage 4: Table Conversion

Financial reports contain extensive HTML tables from OCR. Raw HTML like:

```html
<table border=1><tr><td>Underlying performance</td><td>20,894</td><td>19,696</td></tr></table>
```

is converted to pipe-delimited plain text:

```
Underlying performance | 20,894 | 19,696
```

**Why this matters**: Dense embedding models cannot parse HTML tags semantically. A `<td>` tag carries no meaning to BGE-M3, but "Underlying performance | 20,894" is directly searchable by both dense and sparse vectors.

**Implementation** (`chunker.py:_convert_tables_to_text`): Uses Python's `HTMLParser` to strip tags and produce a row-by-row, cell-by-cell text representation. Applied to all chunk content before storage.

### Stage 5: Section Classification

Each section is classified by type before chunking (`chunker.py:classify_section`):

| Type | Detection | Examples |
|------|-----------|----------|
| `narrative` | Default | CEO letter, business overview |
| `table_heavy` | ≥3 table separators in content | Financial statements |
| `kpi` | Title contains "KPI" or "Financial Highlight" | Key metrics pages |
| `mixed_media` | Contains images | Charts and diagrams |
| `risk_disclosure` | Title contains "risk" or "disclosure" | Risk factor sections |
| `appendix` | Title contains "appendix" or "supplementary" | Supplementary data |

Classification affects the `chunk_type` metadata field stored in Qdrant, which can be used to weight retrieval results.

### Stage 6: Intelligent Chunking

The chunker (`chunker.py:chunk_section`) processes each section with a 512-token target (estimated as `len(text) // 4`).

#### Small sections (≤512 tokens)

The entire section becomes one chunk. Page range is extracted from embedded markers.

#### Large sections (>512 tokens)

Content is split by double-newline paragraphs. Each paragraph is tagged with its page number using **forward propagation**:

```python
def _split_and_tag_paragraphs(self, content):
    """
    Walk paragraphs in order. When a \x00PAGE_NUM\x00 marker is found,
    update current_page. Every paragraph inherits the most recent page.
    """
    paragraphs = re.split(r'\n\n+', content)
    tagged = []
    current_page = None

    for para in paragraphs:
        markers = marker_pattern.findall(para)
        if markers:
            current_page = int(markers[-1])  # Update current page

        clean_text = marker_pattern.sub('', para).strip()
        tagged.append((current_page, clean_text))

    return tagged
```

Paragraphs are then accumulated into chunks respecting the 512-token limit:

```python
for page_num, para_text in tagged_paras:
    if current_tokens + para_tokens > max_tokens and current_paras:
        # Flush current chunk
        pages = [p for p, _ in current_paras if p is not None]
        chunks.append({
            "page_start": min(pages),
            "page_end": max(pages),
            "content": "\n\n".join(t for _, t in current_paras),
        })
        current_paras = [(page_num, para_text)]
    else:
        current_paras.append((page_num, para_text))
```

**Result**: Each chunk knows exactly which page(s) its content comes from, not just which section it belongs to.

## Example: Page-Tracking in Action

Consider a section spanning pages 55-58, with content:

```
\x0055\x00 Introduction paragraph about performance...
\x0056\x00 <table>Underlying performance | 20,894 | 19,696</table>
\x0057\x00 Analysis of underlying trends...
\x0058\x00 Forward-looking statements...
```

After paragraph splitting and page propagation:

| Paragraph | Tagged Page |
|-----------|------------|
| "Introduction paragraph about performance..." | 55 |
| "Underlying performance \| 20,894 \| 19,696" | 56 |
| "Analysis of underlying trends..." | 57 |
| "Forward-looking statements..." | 58 |

If the chunking threshold splits after paragraph 2:

- **Chunk 1**: pages 55-56, content = paragraphs from pages 55 and 56
- **Chunk 2**: pages 57-58, content = paragraphs from pages 57 and 58

Each chunk has accurate `page_start` and `page_end` values, not the section-level range of 55-58.

## Chunk Output Format

Each chunk is stored with the following structure:

```json
{
  "chunk_id": "chunk_0042",
  "chunk_index": 42,
  "section_path": ["Strategic Report", "Financial Highlights"],
  "page_start": 56,
  "page_end": 56,
  "content": "Underlying performance | | | \nOperating income | 20,894 | 19,696 | 6\n...",
  "tokens": 387,
  "chunk_type": "table_heavy"
}
```

After schema conversion, additional fields are added:

```json
{
  "section_title": "Strategic Report > Financial Highlights",
  "content_brief": "Underlying performance | | | \nOperating income | 20,894...",
  "chunk_type": "table",
  "flags": {"is_key_financial_chunk": true},
  "relations": {
    "prev_chunk_id": "chunk_0041",
    "next_chunk_id": "chunk_0043"
  }
}
```

## Why Not Sliding Window?

Financial reports have natural semantic boundaries — sections, subsections, pages, tables. Sliding window chunking would:

1. **Split tables mid-row**: A financial statement table would be split across chunks, making both halves incomplete
2. **Lose section context**: A paragraph about "underlying performance" needs its section title ("Financial Highlights") for retrieval
3. **Create redundant overlap**: Adjacent chunks with 20% overlap would duplicate financial data, wasting storage and confusing retrieval
4. **Destroy page boundaries**: Citations would be unreliable because chunks span arbitrary character offsets, not actual page boundaries

Section-based chunking preserves all of these naturally.

## Metadata Augmentation

Before embedding, each chunk's text is augmented with metadata (`indexer.py:augment_chunk_text`):

```python
def augment_chunk_text(chunk, company_name):
    parts = []
    if company_name:
        parts.append(f"[{company_name}]")          # [Standard Chartered]
    if chunk.period:
        parts.append(f"[{chunk.period.date_label}]") # [FY2025]
    if chunk.section_title:
        parts.append(f"- {chunk.section_title}")    # - Strategic Report > Financial Highlights
    parts.append(chunk.content)
    return "\n".join(parts)
```

This ensures that a query like "Standard Chartered 2025 revenue" can match chunks even if the chunk content doesn't explicitly mention the company name or fiscal year — the metadata prefix fills this gap.
