# Debugging Journal: Lessons Learned

This document records the major issues encountered during development, their root causes, and the solutions applied. Each entry is a case study in debugging a RAG system.

---

## Issue 1: All Citations Showed "Pages 2-99"

### Symptom

Every citation in every answer displayed "Pages 2-99" regardless of actual content location. Clicking different citations showed identical content.

### Root Cause

The `bundle_chunks()` function merged nearly all retrieved chunks into 1-2 mega-bundles because `max_gap=1` (page gap tolerance). In a document with consecutive page numbers (1, 2, 3, ...), chunks from pages 2 through 99 were all within 1 page of each other, so they got merged into a single bundle.

**The bundling logic was:**
```python
if curr_page - prev_page <= max_gap:
    current_bundle.append(curr_chunk)  # Merge!
```

This means page 2 → page 3 (gap 1) → merge, page 3 → page 4 (gap 1) → merge, ... cascading until every chunk was in one bundle.

### Impact

The LLM received essentially the entire document as context, making it no better than brute-force full-document search. Citations were meaningless because the bundle's page range was 2-99.

### Solution

Removed `bundle_chunks()` entirely. Individual chunks are passed directly to the reranker, preserving retrieval granularity. The two-stage reranking pipeline (ColBERT → Cross-Encoder) already handles context selection precisely.

**Lesson**: Chunk bundling sounds good in theory (adjacent pages provide context), but in practice, it destroys the granularity that retrieval and reranking rely on. Let the reranker pick the right chunks.

---

## Issue 2: Answers Became Inaccurate After Removing Bundles

### Symptom

After fixing Issue 1, answers were accurate in page citation but the actual answer quality dropped — responses were shallow and sometimes missed key information.

### Root Cause

With bundles removed, only 3 chunks (the Cross-Encoder's `final_top_k=3`) were provided to the LLM. For a 10-page document with ~50 chunks, 3 chunks captured only ~6% of relevant context.

The previous bundle approach accidentally provided massive context (bad for citations, but comprehensive for answering). Removing it without adjusting retrieval depth left the LLM starved for context.

### Solution

Increased reranking parameters:
- `colbert_top_k`: 10 → 20
- `final_top_k`: 3 → 7

And later implemented dynamic scaling based on document size (see Issue 7).

**Lesson**: When fixing one problem (bad citations), check that you don't accidentally degrade another dimension (answer quality). Always test end-to-end after significant changes.

---

## Issue 3: Citation Content Truncated at 500 Characters

### Symptom

Clicking a citation in the frontend showed only the first 500 characters of the source chunk, cutting off mid-sentence.

### Root Cause

In `chat.py`, citation content was explicitly truncated:
```python
"content": cit.get("content", "")[:500]
```

This was presumably added to limit SSE event size, but it made the citation panel nearly useless for understanding the source.

### Solution

Removed the `[:500]` truncation. SSE event size is not a practical concern for chunks that average 500-1000 characters.

**Lesson**: Don't prematurely optimize network payload size at the cost of user experience. A few KB per citation is negligible.

---

## Issue 4: Chunks Labeled "Pages 4-6" But Content Entirely From Page 5

### Symptom

A chunk's metadata said "Pages 4-6" but its content was entirely from page 5. This made citations misleading.

### Root Cause

Page markers (`\x00{N}\x00`) were only injected at the **start** of each page's content in `build_section_tree()`. When content was split by `\n\n` into paragraphs, only the first paragraph of each page carried the marker. Subsequent paragraphs had no page information and defaulted to the section-level page range.

```
\x005\x00First paragraph of page 5     ← tagged as page 5
Second paragraph of page 5              ← no marker, defaults to section range 4-6
Third paragraph of page 5               ← no marker, defaults to section range 4-6
```

### Solution

Implemented **forward propagation** in `_split_and_tag_paragraphs()`:

```python
current_page = None
for para in paragraphs:
    markers = marker_pattern.findall(para)
    if markers:
        current_page = int(markers[-1])  # Update running page number
    clean_text = marker_pattern.sub('', para).strip()
    tagged.append((current_page, clean_text))  # Every para gets a page
```

Now each paragraph inherits the most recently seen page marker. The chunk's `page_start`/`page_end` is computed from the actual pages of its constituent paragraphs.

**Lesson**: When tracking metadata through transformations, verify that the metadata survives every processing step. Splitting text is a common way to lose positional information.

---

## Issue 5: PDF Upload Produced Worse Chunks Than JSON Upload

### Symptom

Uploading the same document as PDF vs. pre-processed JSON produced drastically different chunk quality. JSON upload gave accurate page ranges and clean chunks; PDF upload gave poor chunks with no page structure.

### Root Cause

Two different code paths with inconsistent data extraction:

- **JSON upload path**: Extracted per-page markdown from `prunedResult.markdown`, built `<!-- PAGE: N -->` markers → chunker received paginated content → good chunks
- **PDF upload path**: Downloaded a page-less markdown blob from Baidu API. Saved the per-page JSON to disk but **never used it for chunking** → chunker treated entire document as one page → terrible chunks

The PDF JSON (`{"pages": [{"markdown": "...", "page_num": 0}]}`) contained identical per-page content, but the code path ignored it.

### Solution

Added `_extract_from_baidu_pdf_json()` to extract paginated markdown from the PDF JSON, producing the same `<!-- PAGE: N -->` format that the JSON upload path uses. Both paths now converge to identical input for the chunker.

**Lesson**: When multiple input paths exist, verify they produce equivalent quality. The easiest way is to normalize them to a single intermediate format early in the pipeline.

---

## Issue 6: 481-Page Document TOC Extraction Failed

### Symptom

Uploading a 481-page Standard Chartered annual report. TOC extraction returned 0 sections. The entire document was chunked as a single section, producing poor results.

### Root Cause

The LLM's `max_tokens` for TOC extraction was set to 1024. For a document with 58 TOC entries, the JSON output was truncated mid-response. The truncated JSON failed to parse, the error was caught, and the system returned an empty TOC.

### Solution

Increased `max_tokens` from 1024 to 4096. For a large annual report, 58 entries × ~30 chars each ≈ 1740 chars of JSON, well within 4096 tokens.

Also improved JSON repair logic: trailing comma removal, fallback to raw extraction from `{` to `}`.

**Lesson**: Token limits for LLM calls should account for worst-case document sizes. For TOC extraction, a 500-page report can easily have 50+ entries.

---

## Issue 7: Pydantic Validation Error `page_start=None`

### Symptom

After fixing Issue 6, the TOC extraction succeeded (58 sections, 1344 chunks), but then the system crashed with:

```
ValidationError: page_start — Input should be a valid integer
```

### Root Cause

Some sections had no content (empty page ranges). These produced chunks with `page_start=None`. The code used:

```python
chunk.get("page_start", 1)  # Only handles missing key, NOT None value
```

In Python, `dict.get("key", default)` returns the default only if the key is missing. If the key exists but has value `None`, the `None` is returned.

### Solution

Changed to:
```python
chunk.get("page_start") or 1  # Handles both missing and None
```

**Lesson**: `dict.get(key, default)` and `dict.get(key) or default` behave differently when the value is `None`. For Pydantic models that require non-null integers, always use the `or` pattern.

---

## Issue 8: Qdrant Collection Not Found After Data Clear

### Symptom

After clearing `qdrant_storage/*` to reset data, the backend returned "Collection not found" errors even after restarting.

### Root Cause

The Qdrant client was initialized as a module-level singleton. Clearing files while the backend was running didn't reset the in-memory client state. New data was written to the deleted storage path.

### Solution

Kill the backend, clear data, then restart. The singleton pattern means state is only initialized on first access.

**Lesson**: Singletons with file-backed storage don't recover from external file deletion. Either add re-initialization logic, or ensure clean restart procedures.

---

## Issue 9: HTML Tables Invisible to Retrieval

### Symptom

Querying "Underlying performance in 2025" returned page 19 (a narrative discussion) instead of page 56 (the actual financial table with the exact data). Direct keyword search in `chunks_raw.json` found page 56 as the top match.

### Root Cause

Page 56's content was a raw HTML `<table>`:
```html
<table border=1><tr><td>Underlying performance</td><td>20,894</td>...
```

BGE-M3's dense encoder doesn't understand HTML tags. The embedding for `<td style='text-align: center'>Underlying performance</td>` is semantically similar to any other HTML-heavy content, not to a query about "underlying performance". The sparse vector partially matched "Underlying", but RRF fusion weighted the dense signal more heavily.

### Solution

Convert all HTML tables to pipe-delimited plain text during chunking:
```
Underlying performance | 20,894 | 19,696 | 6
Operating expenses | (12,347) | (11,790) | (5)
```

This preserves all data while making it directly readable by both dense and sparse encoders.

**Lesson**: OCR output format matters for retrieval quality. Always inspect what the embedding model actually "sees" — raw HTML tags are noise that dilutes semantic matching.

---

## Issue 10: Large Documents Had Insufficient Retrieval Coverage

### Symptom

A 481-page document (~1300 chunks) had poor answer quality. Questions that should have been answerable returned "Based on the provided documents, this question cannot be answered."

### Root Cause

Fixed retrieval parameters (80 retrieve → 20 ColBERT → 7 final) worked for small documents (~50 chunks, 160% coverage) but were woefully inadequate for large documents (~1300 chunks, 6% coverage). Most relevant chunks were never retrieved.

### Solution

Implemented dynamic parameter scaling:

```python
retrieve_limit = min(300, max(80, total_chunks // 5))  # ~20% coverage
colbert_top_k  = min(50, max(20, retrieve_limit // 3))
final_top_k    = min(15, max(7, colbert_top_k // 3))
```

**Lesson**: Retrieval depth must scale with document size. Fixed parameters that work for test data will fail on production-scale documents.

---

## Issue 11: Prompt Format String Crashes

### Symptom

LLM calls for metadata extraction crashed with `KeyError` exceptions.

### Root Cause

The metadata extraction prompt contained JSON examples with curly braces:
```python
prompt = '{"keywords": ["rerevenue", "net income"]}'
result = prompt.format(user_query=query)  # KeyError: 'keywords'
```

Python's `str.format()` treats `{keywords}` as a format placeholder.

### Solution

Escaped all curly braces in prompt templates: `{` → `{{`, `}` → `}}`.

**Lesson**: When using `str.format()` for prompt templates, always escape literal curly braces in JSON examples. Consider using f-strings or string concatenation instead.

---

## Summary of Lessons

| Category | Lesson |
|----------|--------|
| **Chunking** | Never bundle chunks — let reranking handle context selection |
| **Metadata** | Forward-propagate positional metadata through all transformations |
| **Data paths** | Normalize all input paths to a single intermediate format |
| **LLM limits** | Set `max_tokens` based on worst-case document size |
| **Python dicts** | `dict.get(key, default)` ≠ `dict.get(key) or default` for None values |
| **Retrieval** | Scale parameters with document size, not fixed values |
| **OCR output** | Strip HTML before embedding — tags are noise to vector models |
| **Format strings** | Escape `{` `}` in prompt templates that use `.format()` |
| **Singletons** | File-backed singletons don't recover from external data deletion |
| **End-to-end testing** | Always verify the full pipeline after fixing individual components |

These issues collectively demonstrate that building a RAG system is not just about choosing the right models — the engineering of data flow, metadata tracking, and parameter tuning is equally critical to answer quality.
