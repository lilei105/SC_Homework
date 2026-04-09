# Technology Selection Rationale

## Overview

This document explains why each major technology was chosen for the Financial Report RAG system. For each choice, we describe the alternatives considered, the decision criteria, and the trade-offs accepted.

---

## 1. OCR: Baidu PaddleOCR-VL

### Why we need OCR

Users upload PDF financial reports. The system needs structured, page-aware text extraction to enable accurate chunking with page-level citations.

### Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **PyMuPDF (fitz)** | Fast, local, no API cost | No table structure preservation; layout loss on complex PDFs |
| **Tesseract OCR** | Free, open-source | Poor accuracy on financial tables; no layout understanding |
| **Azure Document Intelligence** | Good table extraction, layout analysis | Higher cost, US-only data residency |
| **Google Document AI** | Strong OCR quality | Complex setup, per-page pricing |
| **Baidu PaddleOCR-VL** | Free tier, good Chinese+English, preserves table structure | API dependency, Chinese documentation, rate limits |

### Decision: Baidu PaddleOCR-VL

**Key reasons:**
1. **Table preservation**: Financial reports are table-heavy. PaddleOCR-VL returns tables as HTML, preserving cell structure. PyMuPDF would flatten tables into unstructured text.
2. **Per-page structure**: Returns `{"pages": [{"page_num": 0, "markdown": "..."}]}` — critical for page-level citation tracking.
3. **Free tier**: Generous free tier suitable for a homework project.
4. **Bilingual support**: Handles both English (most financial reports) and Chinese content well.

**Trade-off accepted**: API latency (~30-60s for a 100-page PDF) and dependency on external service. Mitigated by saving OCR results to disk for reuse.

---

## 2. Embedding Model: BAAI/bge-m3

### Why we need embeddings

To enable semantic search over document chunks, we need to convert both queries and chunks into vector representations.

### Alternatives Considered

| Option | Dense | Sparse | ColBERT | Multilingual |
|--------|-------|--------|---------|-------------|
| **OpenAI text-embedding-3-large** | Yes (3072d) | No | No | Yes |
| **Cohere embed-v3** | Yes (1024d) | No | No | Yes |
| **BAAI/bge-large-en-v1.5** | Yes (1024d) | No | No | English only |
| **BAAI/bge-m3** | Yes (1024d) | Yes | Yes | Yes |
| **nomic-embed-text** | Yes (768d) | No | No | English only |

### Decision: BAAI/bge-m3

**Key reasons:**
1. **Triple representation**: A single model produces dense vectors, sparse lexical weights, AND ColBERT embeddings. This eliminates the need for separate BM25 and dense models.
2. **No API dependency**: Runs locally on GPU. No per-query embedding cost, no rate limits on retrieval.
3. **Financial domain**: BGE models are trained on diverse corpora including financial text. The dense vectors handle synonyms well (revenue ≈ turnover ≈ income).
4. **Sparse vectors**: BM25-style sparse weights capture exact matches ("$20,894 million", "Q3 2025") that dense vectors might miss.
5. **ColBERT for reranking**: Token-level embeddings enable fine-grained reranking without loading a separate model.

**Trade-off accepted**: Requires ~2.2 GB GPU VRAM. Not viable on CPU-only systems.

**Why not use separate models?** Using one model for dense + sparse + ColBERT means:
- Single model load (2.2 GB vs 3+ GB for multiple models)
- Consistent tokenization across all retrieval signals
- Simpler codebase (one model object, one encode call)

---

## 3. Vector Database: Qdrant

### Why we need a vector database

We need to store 1000+ chunk embeddings per document and perform fast similarity search with filtering.

### Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **FAISS** | Fast, battle-tested, local | No native sparse vector support; no CRUD operations |
| **Milvus** | Distributed, sparse support | Heavy setup (etcd, MinIO); overkill for single-node |
| **Chroma** | Simple Python API, local | Immature; sparse support is limited; poor filtering |
| **Pinecone** | Managed, scalable | Cloud-only; per-query pricing; no local mode |
| **Weaviate** | Multi-modal, GraphQL API | Heavier runtime; overkill for this use case |
| **Qdrant** | Local file mode, native sparse + dense, RRF fusion | Rust dependency (but has Python client) |

### Decision: Qdrant (local file mode)

**Key reasons:**
1. **Native hybrid search**: Supports named vectors for dense + sparse in a single collection, with built-in RRF fusion. No manual score combination needed.
2. **Local file mode**: `QdrantClient(path="./data/qdrant_storage")` — no server to run, data stored as local files. Perfect for a homework project.
3. **RRF fusion**: Built-in Reciprocal Rank Fusion combines dense and sparse search results. We'd have to implement this ourselves with FAISS.
4. **Filtering**: Document-scoped filtering (`document_id = X`) is native and efficient.
5. **Point count**: `client.count()` enables dynamic retrieval parameter scaling.

**Trade-off accepted**: Local file mode doesn't scale to multi-server deployments. For production, Qdrant can be run as a separate service.

**Why not FAISS?** FAISS is great for pure dense search, but lacks:
- Sparse vector support (we'd need a separate BM25 implementation)
- Native CRUD (can't update/delete individual points easily)
- Metadata filtering (no `WHERE document_id = X`)
- RRF fusion (would need manual implementation)

---

## 4. Reranker: BAAI/bge-reranker-v2-gemma

### Why we need reranking

Initial retrieval (dense + sparse) returns many candidates. Reranking re-scores them with a more expensive model to pick the most relevant ones.

### Alternatives Considered

| Option | Type | Pros | Cons |
|--------|------|------|------|
| **Cohere Rerank** | API | Easy to use, strong quality | Per-query cost, API dependency |
| **bge-reranker-base** | Cross-Encoder | Small (280M params), fast | Lower accuracy on financial text |
| **bge-reranker-large** | Cross-Encoder | Better accuracy | Larger, slower |
| **bge-reranker-v2-gemma** | Cross-Encoder | Highest accuracy, Gemma-based | Largest (~2B params), most GPU VRAM |
| **MonoT5** | Seq2Seq | Good general performance | Not specialized for financial text |

### Decision: bge-reranker-v2-gemma

**Key reasons:**
1. **Best-in-class accuracy**: Built on Gemma 2B, significantly outperforms smaller rerankers on complex queries.
2. **Same ecosystem as BGE-M3**: Consistent tokenization, well-tested integration.
3. **Financial text**: The Gemma backbone has stronger language understanding for financial terminology and numerical reasoning.
4. **No API dependency**: Runs locally on GPU.

**Trade-off accepted**: ~4 GB GPU VRAM. Combined with BGE-M3 (~2.2 GB), total GPU requirement is ~6.5 GB. Fits on consumer GPUs (RTX 3060 8GB, RTX 4060 8GB).

**Why two-stage (ColBERT + Cross-Encoder) instead of Cross-Encoder only?**
- Cross-Encoder on 260 candidates: ~10s per query (too slow)
- ColBERT on 260 candidates → 50: ~0.5s
- Cross-Encoder on 50 candidates: ~1.5s
- **Total: ~2s** — 5× faster than Cross-Encoder only

---

## 5. LLM: Qwen Turbo (via Alibaba Dashscope)

### Why we need an LLM

Used for: query rewriting, TOC extraction, document metadata extraction, and answer generation.

### Alternatives Considered

| Option | Pros | Cons |
|--------|------|------|
| **OpenAI GPT-4o-mini** | Strong quality, cheap | Requires international payment; API region restrictions |
| **Claude Haiku** | Fast, cheap | Requires Anthropic API key |
| **Qwen Turbo** | Very cheap, fast, good Chinese+English | Weaker on complex reasoning |
| **Local Llama 3** | Free, private | Requires 8+ GB VRAM (conflicts with embedding models) |
| **DeepSeek V3** | Strong reasoning, cheap | Higher latency |

### Decision: Qwen Turbo

**Key reasons:**
1. **Cost**: ~¥0.0003/1K tokens — effectively free for a homework project.
2. **Speed**: First-token latency ~200ms. Critical for streaming Q&A.
3. **Bilingual**: Handles Chinese prompts (used by the developer) and English financial text equally well.
4. **Dashscope compatibility**: OpenAI-compatible API, easy integration with existing tooling.

**Trade-off accepted**: Weaker complex reasoning compared to GPT-4 or Claude. For financial Q&A with good context (reranked chunks), this is sufficient.

**Why not local LLM?** BGE-M3 (~2.2 GB) + bge-reranker (~4 GB) already use ~6.5 GB VRAM. Running Llama 3 (8B) would require another ~5 GB, exceeding consumer GPU capacity.

---

## 6. Backend Framework: FastAPI

### Why FastAPI

| Requirement | FastAPI | Flask | Django |
|------------|---------|-------|--------|
| Async SSE streaming | Native | Requires extensions | Complex |
| Type validation (Pydantic) | Built-in | Manual | Manual |
| Auto-generated API docs | Built-in | Separate package | Separate package |
| Performance | High (ASGI) | Medium (WSGI) | Medium (WSGI) |

**Decision**: FastAPI for native async support (essential for SSE streaming), built-in Pydantic validation, and automatic OpenAPI docs.

---

## 7. Frontend: React + TypeScript + TailwindCSS

### Why React

| Requirement | React | Vue | Svelte |
|------------|-------|------|--------|
| SSE event handling | Full control | Full control | Full control |
| TypeScript support | Excellent | Good | Good |
| Component ecosystem | Largest | Large | Growing |
| Tailwind integration | Excellent | Excellent | Excellent |

**Decision**: React for the largest ecosystem and best TypeScript support. No state management library (Redux/Zustand) needed — the app is simple enough with `useState` and a custom `useChat` hook.

### Why TailwindCSS over styled-components or CSS modules

1. **Rapid prototyping**: Utility classes for fast iteration
2. **No context switching**: Styles inline in JSX, no separate CSS files
3. **Small bundle**: Only used classes are included in production build

---

## 8. Why Qdrant Local Mode (not Docker)

For a homework project, running `QdrantClient(path="./data/qdrant_storage")` directly is simpler than:
- Installing Docker
- Managing a separate Qdrant container
- Configuring networking between services
- Handling container lifecycle

Local file mode stores data directly on disk. Performance is identical for single-node workloads.

---

## Summary

| Component | Choice | Primary Reason |
|-----------|--------|---------------|
| OCR | Baidu PaddleOCR-VL | Free, table structure, per-page output |
| Embedding | BAAI/bge-m3 | Triple representation (dense + sparse + ColBERT) in one model |
| Vector DB | Qdrant (local) | Native hybrid search with RRF, local file mode |
| Reranker | bge-reranker-v2-gemma | Best accuracy, same BGE ecosystem |
| LLM | Qwen Turbo | Cheap, fast, bilingual |
| Backend | FastAPI | Native async + SSE + Pydantic |
| Frontend | React + TypeScript | Ecosystem, type safety |
| Styling | TailwindCSS | Rapid development |

**Total GPU VRAM required**: ~6.5 GB (BGE-M3: 2.2 GB + bge-reranker: 4 GB)
**LLM cost per query**: ~¥0.01 (~$0.001)
**OCR cost per document**: Free tier
