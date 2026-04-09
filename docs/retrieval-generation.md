# Retrieval & Generation Pipeline

## Overview

This document covers the query-time pipeline: from a user's question to a streaming, citation-backed answer. The core design revolves around **BGE-M3's multi-representation capabilities** — a single model that produces dense vectors, sparse lexical weights, and ColBERT token-level embeddings.

```
User Query
    │
    ├──► Query Rewriting (LLM → 3 variants)
    │         │
    │         ▼
    ├──► BGE-M3 Encoding (Dense + Sparse per query)
    │         │
    │         ▼
    ├──► Qdrant Hybrid Search (RRF Fusion) × 3 queries
    │         │
    │         ▼
    ├──► Deduplicate by chunk_id, keep best score
    │         │
    │         ▼
    ├──► ColBERT MaxSim Reranking (coarse → top 20-50)
    │         │
    │         ▼
    ├──► Cross-Encoder Reranking (fine → top 7-15)
    │         │
    │         ▼
    └──► Streaming LLM Generation + Citation Extraction
```

## 1. Query Rewriting

### Problem

Users often ask vague or imprecise questions:
- "What's the underlying performance in 2025?" — may not match exact terms in the document
- "2024年Q3营收多少" — Chinese query against an English document
- "How did they do?" — extremely vague, needs expansion

### Solution: Multi-Query Expansion

The LLM rewrites each query into **3 retrieval-friendly variants**:

```json
// Input: "What's the underlying performance in 2025?"
{
  "rewritten": "2025 underlying performance operating income profit financial results",
  "alternatives": [
    "2025 year underlying profit before taxation earnings growth",
    "FY2025 underlying operating performance metrics compared to prior year"
  ]
}
```

**Prompt design** (`prompts.py:QUERY_REWRITE_PROMPT`):
- Translates non-English queries to English
- Expands financial abbreviations (Q3 → third quarter)
- Adds relevant synonyms (revenue → turnover/income/sales)
- Each query under 20 words
- Output as structured JSON

**Fallback**: If the LLM call fails (rate limit, timeout), the system falls back to using only the original query.

### Implementation

```python
# llm_client.py
def rewrite_query(user_query: str) -> List[str]:
    """Returns list of 1-3 query strings."""
    try:
        response = chat_completion(...)
        data = json.loads(response)
        return [data["rewritten"]] + data.get("alternatives", [])
    except Exception:
        return [user_query]  # Graceful fallback
```

## 2. BGE-M3 Multi-Representation Encoding

BGE-M3 is the backbone of the retrieval system. The "M3" stands for **Multi-lingual**, **Multi-granularity**, and **Multi-function** — a single model that produces three types of representations.

### Dense Vectors (1024-dimensional)

Capture semantic meaning — "profit" and "net income" produce similar vectors even though they share no words.

```python
# indexer.py - during indexing
embeddings = model.encode(
    batch,
    return_dense=True,       # 1024-dim float vectors
    return_sparse=True,      # BM25-style lexical weights
    return_colbert_vecs=False # Skip ColBERT for storage (computed on-demand)
)
```

### Sparse Vectors (Lexical Weights)

BM25-style term weighting that captures exact token matches. Critical for financial documents where specific numbers matter:
- Query: "2025 revenue $20,894 million"
- Sparse vector will strongly match chunks containing exactly "$20,894" or "revenue"

```python
query_sparse = query_emb['lexical_weights'][0]
# Dict[int, float] mapping token IDs to weights
```

### ColBERT Vectors (Computed On-Demand)

Token-level embeddings that enable fine-grained matching via MaxSim. Not stored — computed during reranking to save storage.

```python
# reranker.py - during reranking
query_emb = model.encode([query], return_colbert_vecs=True)
query_colbert = query_emb['colbert_vecs'][0]  # [seq_len, 128]
```

### Why Not Store ColBERT?

For a 1300-chunk document:
- Dense: 1300 × 1024 × 4 bytes = ~5 MB
- Sparse: 1300 × ~100 entries = ~0.5 MB
- ColBERT: 1300 × ~128 tokens × 128 dims × 4 bytes = ~85 MB

ColBERT vectors would increase storage 15× with marginal retrieval benefit since they are only used during the reranking stage. Computing them on-demand from the original text takes ~1 second for 50 candidates.

## 3. Qdrant Hybrid Search with RRF

### Collection Design

```python
# qdrant_client.py
client.create_collection(
    collection_name="financial_reports",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE)
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams()
    }
)
```

Named vectors allow independent configuration of dense and sparse search parameters.

### RRF (Reciprocal Rank Fusion)

Qdrant natively supports hybrid search via RRF — a rank-based fusion method that combines results from multiple retrieval paths:

```python
# qdrant_client.py:hybrid_search
results = client.query_points(
    prefetch=[
        Prefetch(query=sparse_vector, using="sparse", limit=limit, ...),
        Prefetch(query=dense_vector,  using="dense",  limit=limit, ...),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=limit,
    with_payload=True
)
```

**How RRF works**:
1. Dense search returns ranked list A
2. Sparse search returns ranked list B
3. For each document, compute: `score = Σ(1 / (k + rank))` where k=60 (Qdrant default)
4. Final ranking by combined score

**Why RRF over weighted sum**: RRF is rank-based, not score-based. This means it doesn't matter if dense scores are in [0,1] and sparse scores are unbounded — the fusion is robust to score scale differences.

### Multi-Query Retrieval

Each of the 3 rewritten queries is independently encoded and searched:

```python
# retriever.py
seen = {}  # chunk_id → best score

for i in range(len(queries)):
    query_dense = query_embs['dense_vecs'][i].tolist()
    query_sparse = query_embs['lexical_weights'][i]

    results = hybrid_search(query_dense, query_sparse, document_id, limit)
    for point in results:
        cid = point.payload.get("chunk_id")
        if cid not in seen or point.score > seen[cid]["score"]:
            seen[cid] = {..., "score": point.score}

# Sort by score descending
return sorted(seen.values(), key=lambda x: x["score"], reverse=True)
```

**Deduplication**: If the same chunk appears in results from multiple queries, only the highest score is kept.

## 4. Two-Stage Reranking

### Stage 1: ColBERT MaxSim

ColBERT (Contextualized Late Interaction over BERT) uses token-level embeddings for fine-grained matching.

**How MaxSim works**:

For each query token Q_i, find the maximum similarity with any document token:

```
Score(Q, D) = Σ_i  max_j  cos(Q_i, D_j)
```

This captures token-level interactions that dense vectors miss:
- Query: "underlying performance"
- Dense might rank "reported performance" similarly (semantically close)
- ColBERT distinguishes "underlying" vs "reported" at the token level

```python
# reranker.py:colbert_rerank
query_colbert = model.encode([query], return_colbert_vecs=True)['colbert_vecs'][0]
context_colberts = model.encode(context_texts, return_colbert_vecs=True)['colbert_vecs']

scores = [model.colbert_score(query_colbert, ctx) for ctx in context_colberts]
```

### Stage 2: Cross-Encoder (BGE-reranker-v2-gemma)

The Cross-Encoder takes (query, document) pairs and produces a single relevance score through full attention across both texts.

```python
# reranker.py:cross_encoder_rerank
pairs = [[query, c.get("content", "")] for c in contexts]
scores = reranker.compute_score(pairs, normalize=True)
```

**Why Cross-Encoder is slower but better**: Unlike bi-encoders (dense vectors) that encode query and document separately, Cross-Encoders process them jointly. This allows cross-attention between query tokens and document tokens, capturing nuanced relationships like:
- Negation ("excluding restructuring charges")
- Conditional statements ("if we adjust for...")
- Comparative relationships ("increased by 6% year-over-year")

### Why Two Stages?

| Aspect | ColBERT | Cross-Encoder |
|--------|---------|---------------|
| Speed | Fast (~0.5s for 200 candidates) | Slow (~2s for 50 candidates) |
| Precision | Token-level, good for exact terms | Deep semantic, good for nuance |
| Scalability | Linear with candidates | Quadratic with text length |
| Role | Coarse filter | Precision selector |

ColBERT efficiently reduces 200+ candidates to 20-50, then Cross-Encoder applies expensive deep scoring on this manageable set.

## 5. Streaming Generation with Citations

### Context Formatting

Retrieved chunks are formatted with source numbers for the LLM:

```python
# generator.py:format_context
formatted.append(
    f"---\n[Source 1: Strategic Report > Financial Highlights (Page 56)]\n"
    f"Underlying performance | | | \nOperating income | 20,894 | 19,696 | 6\n---"
)
```

### Answer Generation

The LLM generates answers with `[Source N]` citations:

```
The underlying operating income in 2025 was $20,894 million, representing
a 6% increase from $19,696 million in 2024 [Source 1]. Profit before
taxation reached $7,900 million, up 16% year-over-year [Source 1].
```

### Citation Extraction

Citations are extracted in real-time as tokens stream in:

```python
# generator.py:generate_answer
for token in generate_answer_stream(query, context_str):
    accumulated_text += token
    cited_sources = extract_citations(accumulated_text)
    for source_num in cited_sources:
        if source_num not in seen_sources:
            # Map source_num → context → citation with page info
            citations.append({
                'source_num': source_num,
                'page_start': ctx['page_start'],
                'page_end': ctx['page_end'],
                'page_label': f"Page {page_start}",
                'content': ctx['content'],
                'section_title': ctx['section_title'],
            })
    yield token, citations
```

### SSE Streaming

The `chat.py` endpoint yields Server-Sent Events:

```python
async def event_generator():
    for token, new_citations in generate_answer(query, top_contexts):
        yield json.dumps({"type": "token", "content": token})
        for cit in new_citations:
            yield json.dumps({
                "type": "citation",
                "source_num": cit["source_num"],
                "page_label": cit["page_label"],
                "content": cit["content"],
                "section_title": cit["section_title"],
            })
        await asyncio.sleep(0.01)
    yield json.dumps({"type": "done"})
```

## Dynamic Parameter Scaling

All retrieval and reranking parameters scale with document size:

```python
# chat.py
total_chunks = count_document_chunks(document_id)
retrieve_limit = min(300, max(80, total_chunks // 5))
colbert_top_k  = min(50, max(20, retrieve_limit // 3))
final_top_k    = min(15, max(7, colbert_top_k // 3))
```

**Why dynamic?** A 10-page document produces ~50 chunks — retrieving 80 catches most relevant content. A 400-page document produces ~1300 chunks — the same 80 would be only 6% coverage, missing most relevant passages. Scaling ensures ~20% coverage regardless of document size.

| Document Size | Total Chunks | Retrieve | ColBERT | Cross-Encoder |
|--------------|-------------|----------|---------|---------------|
| 10 pages     | ~50         | 80       | 26      | 8             |
| 100 pages    | ~200        | 80       | 26      | 8             |
| 200 pages    | ~600        | 120      | 40      | 13            |
| 400+ pages   | ~1300       | 260      | 50      | 15            |

## Cost Profile

For a single Q&A query on a 1300-chunk document:

| Step | Time | Notes |
|------|------|-------|
| Query rewrite (LLM) | ~0.5s | 1 LLM call |
| Encode 3 queries (BGE-M3) | ~0.3s | 3 forward passes |
| Qdrant search × 3 | ~0.1s | Local SSD, RRF fusion |
| ColBERT rerank | ~0.5s | Encode 260 chunks |
| Cross-Encoder rerank | ~1.5s | Score 50 pairs |
| Answer generation (LLM) | ~3-5s | Streaming with thinking mode |
| **Total** | **~6-8s** | ~2s before first token |

**GPU required**: BGE-M3 and BGE-reranker require CUDA. All model inference runs on GPU; only the LLM calls go through the cloud API.
