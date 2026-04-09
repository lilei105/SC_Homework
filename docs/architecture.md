# System Architecture

## Overview

This is a **Financial Report RAG (Retrieval-Augmented Generation) system** that enables intelligent question-answering on financial documents such as annual reports and quarterly filings. Users upload PDF or pre-processed OCR documents, and the system processes them through a multi-stage pipeline to provide accurate, citation-backed answers.

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Backend** | FastAPI (Python 3.12) | Async API server with SSE streaming |
| **Frontend** | React 18 + TypeScript + TailwindCSS | Responsive SPA with real-time updates |
| **Vector DB** | Qdrant (local file mode) | Hybrid dense + sparse vector storage |
| **Embedding** | BAAI/bge-m3 (FlagEmbedding) | Dense + Sparse + ColBERT multi-representation |
| **Reranker** | BAAI/bge-reranker-v2-gemma | Cross-Encoder for precision reranking |
| **LLM** | Qwen Turbo (via Alibaba Dashscope) | Query rewriting, answer generation |
| **OCR** | Baidu PaddleOCR-VL | PDF-to-markdown conversion with page structure |
| **Build** | Vite | Frontend bundler |

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (React SPA)                      │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ Sidebar   │  │ ChatBox      │  │ Citation Panel            │  │
│  │ Doc List  │  │ Messages     │  │ Source content preview    │  │
│  │ Upload    │  │ Input        │  │ Page number display       │  │
│  └──────────┘  └──────────────┘  └───────────────────────────┘  │
│       │               │ SSE                        │              │
└───────┼───────────────┼────────────────────────────┼─────────────┘
        │               │                            │
        ▼               ▼                            │
┌────────────────────────────────────────────────────┼─────────────┐
│                     FastAPI Backend                 │             │
│                                                     │             │
│  ┌──────────────────────────────────────────────┐  │             │
│  │            API Endpoints                      │  │             │
│  │  POST /documents    → Upload + Process        │  │             │
│  │  GET  /documents    → List all documents      │  │             │
│  │  GET  /chat         → SSE Q&A stream          │  │             │
│  └──────────────────────────────────────────────┘  │             │
│                                                     │             │
│  ╔═══════════════════════════════════════════════╗  │             │
│  ║       INDEXING PIPELINE (Background)          ║  │             │
│  ║                                               ║  │             │
│  ║  PDF ──► PaddleOCR-VL ──► Page Parser         ║  │             │
│  ║            │             │                     ║  │             │
│  ║            ▼             ▼                     ║  │             │
│  ║        OCR JSON     TOC Extraction (LLM)       ║  │             │
│  ║                          │                     ║  │             │
│  ║                          ▼                     ║  │             │
│  ║                    Section Tree Builder         ║  │             │
│  ║                          │                     ║  │             │
│  ║                          ▼                     ║  │             │
│  ║              Table Conversion + Chunking        ║  │             │
│  ║                          │                     ║  │             │
│  ║                          ▼                     ║  │             │
│  ║               BGE-M3 Encoder (Dense+Sparse)    ║  │             │
│  ║                          │                     ║  │             │
│  ║                          ▼                     ║  │             │
│  ║                    Qdrant Upsert                ║  │             │
│  ╚═══════════════════════════════════════════════╝  │             │
│                                                     │             │
│  ╔═══════════════════════════════════════════════╗  │             │
│  ║       QUERY PIPELINE (Real-time)               ║  │             │
│  ║                                               ║  │             │
│  ║  User Query                                   ║  │             │
│  ║      │                                        ║  │             │
│  ║      ▼                                        ║  │             │
│  ║  Query Rewriting (LLM → 3 variants)           ║  │             │
│  ║      │                                        ║  │             │
│  ║      ▼                                        ║  │             │
│  ║  Multi-Query Retrieval (BGE-M3 + Qdrant RRF)  ║  │             │
│  ║      │                                        ║  │             │
│  ║      ▼                                        ║  │             │
│  ║  Two-Stage Reranking                          ║  │             │
│  ║    ├─ Stage 1: ColBERT MaxSim                 ║  │             │
│  ║    └─ Stage 2: Cross-Encoder (Gemma)          ║  │             │
│  ║      │                                        ║  │             │
│  ║      ▼                                        ║  │             │
│  ║  Streaming Generation (Qwen + Citations)       ║  │             │
│  ╚═══════════════════════════════════════════════╝  │             │
│                                                     │             │
└─────────────────────────────────────────────────────┼─────────────┘
                                                      │
        ┌─────────────────────────────────────────────┘
        ▼
  ┌───────────────┐
  │    Qdrant      │
  │  Vector Store  │
  │  Dense (1024d) │
  │  Sparse (BM25) │
  └───────────────┘
```

## Three-Stage Pipeline

### Stage 1: Indexing Pipeline

The indexing pipeline processes uploaded documents into searchable vector representations.

```
Upload → OCR → Page Parsing → TOC Extraction → Section Tree → Chunking → Embedding → Storage
```

**Key characteristics:**
- **LLM-powered TOC extraction**: Uses Qwen to detect and parse table of contents from first 5 pages
- **Section-aware chunking**: Preserves document semantic structure, ~512 tokens per chunk
- **HTML table conversion**: Replaces HTML `<table>` with pipe-delimited plain text for better retrieval
- **Precise page tracking**: Null-byte page markers track which page each paragraph belongs to
- **Metadata augmentation**: Prepends company name, period, and section title to chunk content before embedding

Processing artifacts saved per document in `data/tasks/{document_id}/`:

```
ocr_result.md       # Full OCR markdown
ocr_result.json     # Structured page data from OCR
toc.json            # Extracted table of contents
section_tree.json   # Section hierarchy with content
chunks_raw.json     # All chunks before embedding
document.json       # Final document schema
```

### Stage 2: Retrieval Pipeline

The retrieval pipeline finds relevant chunks using multi-signal hybrid search.

```
Query → Rewrite (3 variants) → Encode (Dense+Sparse) → Qdrant RRF → Deduplicate
```

**Key characteristics:**
- **Multi-query expansion**: LLM rewrites user query into 3 variants (1 main + 2 alternatives)
- **Hybrid search**: Dense vectors capture semantics, sparse vectors capture exact terms
- **RRF fusion**: Reciprocal Rank Fusion balances dense and sparse results in Qdrant
- **Dynamic scaling**: Retrieval parameters adapt to document size

Dynamic parameter scaling (`chat.py`):

```python
retrieve_limit = min(300, max(80, total_chunks // 5))   # ~20% coverage
colbert_top_k  = min(50, max(20, retrieve_limit // 3))  # Coarse rerank
final_top_k    = min(15, max(7, colbert_top_k // 3))    # Fine rerank
```

| Document Size | Retrieve | ColBERT | Cross-Encoder |
|--------------|----------|---------|---------------|
| ~200 chunks  | 80       | 26      | 8             |
| ~600 chunks  | 120      | 40      | 13            |
| ~1300 chunks | 260      | 50      | 15            |

### Stage 3: Reranking & Generation Pipeline

Precision ranking and answer generation with source citations.

```
Retrieved Chunks → ColBERT MaxSim → Cross-Encoder → Context Formatting → Streaming LLM → Citations
```

**Key characteristics:**
- **Two-stage reranking**: ColBERT (fast, token-level) → Cross-Encoder (deep, semantic)
- **Streaming SSE**: Tokens sent to frontend in real-time as generated
- **Source-based citations**: `[Source N]` format maps directly to context list index
- **Real-time citation injection**: Citations extracted and sent as separate SSE events

## API Design

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/documents` | Upload PDF or JSON document |
| `GET` | `/api/v1/documents` | List all documents with metadata |
| `GET` | `/api/v1/documents/{id}/status` | Poll processing status |
| `DELETE` | `/api/v1/documents/{id}` | Remove document and indexed data |
| `GET` | `/api/v1/chat` | Stream Q&A response (SSE) |
| `POST` | `/api/v1/chat` | Same as GET (SSE wrapper) |

### SSE Event Types

The chat endpoint returns a stream of Server-Sent Events:

```json
{"type": "token", "content": "The underlying"}
{"type": "token", "content": " profit before"}
{"type": "citation", "source_num": 1, "page_label": "Page 56", "content": "...", "section_title": "Financial Highlights"}
{"type": "done"}
```

| Event | Description |
|-------|-------------|
| `token` | Partial answer text (streamed token by token) |
| `citation` | Reference to a source chunk with page, section, and content |
| `done` | Stream complete |
| `error` | Error message |

## Frontend Architecture

```
src/
├── App.tsx                    # Main layout with resizable sidebar
├── types/index.ts             # TypeScript interfaces mirroring backend schemas
├── services/api.ts            # Axios API client
├── hooks/useChat.ts           # Chat state management + SSE event handling
└── components/
    ├── Layout/
    │   ├── Sidebar.tsx        # Document list, upload, status polling
    │   └── Header.tsx         # Document title display
    ├── Document/
    │   ├── UploadModal.tsx     # Drag-and-drop upload with validation
    │   └── DocList.tsx         # Document cards with status indicators
    └── Chat/
        ├── ChatBox.tsx         # Message list + citation panel
        ├── Message.tsx         # Markdown rendering + citation buttons
        └── InputArea.tsx       # Multi-line input with Enter/Shift+Enter
```

**Key frontend features:**
- **Resizable sidebar** (200-600px) for document navigation
- **Auto-polling** (2s interval) for document processing status
- **SSE streaming** with progressive rendering of answer and citations
- **Citation panel** that shows source chunk content on click
- **Drag-and-drop** file upload with size/type validation

## Backend Architecture

```
backend/app/
├── main.py                          # FastAPI app entry point
├── core/
│   ├── config.py                    # Pydantic settings (env vars)
│   └── prompts.py                   # LLM prompt templates
├── models/
│   └── schemas.py                   # Pydantic data models
├── api/endpoints/
│   ├── documents.py                 # Upload, list, status, delete
│   └── chat.py                      # SSE streaming Q&A
├── services/
│   ├── baidu_ocr.py                 # Baidu PaddleOCR-VL API client
│   ├── chunker.py                   # Document chunking (TOC, sections, pages)
│   ├── indexer.py                   # BGE-M3 encoding + Qdrant upsert
│   ├── retriever.py                 # Multi-query hybrid retrieval
│   ├── reranker.py                  # ColBERT + Cross-Encoder two-stage reranking
│   ├── generator.py                 # Streaming answer generation + citation extraction
│   ├── llm_client.py               # Qwen LLM client (sync/stream/async)
│   └── metadata_extractor.py       # LLM-based chunk metadata enrichment
└── utils/
    └── qdrant_client.py            # Qdrant CRUD + hybrid search with RRF
```

## Configuration

All settings are managed via environment variables with Pydantic validation:

| Variable | Default | Description |
|----------|---------|-------------|
| `DASHSCOPE_API_KEY` | — | Alibaba Dashscope API key for LLM |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/...` | Dashscope API endpoint |
| `DASHSCOPE_MODEL` | `qwen-turbo` | LLM model for generation |
| `BAIDU_OCR_API_KEY` | — | Baidu OCR API key |
| `BAIDU_OCR_SECRET_KEY` | — | Baidu OCR secret key |
| `QDRANT_PATH` | `./data/qdrant_storage` | Local Qdrant storage path |
| `COLLECTION_NAME` | `financial_reports` | Qdrant collection name |
| `EMBEDDING_MODEL_NAME` | `BAAI/bge-m3` | Embedding model |
| `RERANKER_MODEL_NAME` | `BAAI/bge-reranker-v2-gemma` | Cross-Encoder reranker model |

## Design Principles

1. **No speculative abstractions**: Each component exists because the pipeline requires it
2. **Section-aware chunking**: Financial reports have natural semantic boundaries (sections, pages) — we preserve these instead of using sliding windows
3. **Multi-signal retrieval**: No single retrieval method works for all queries — combining dense semantics, sparse keywords, and ColBERT token matching maximizes recall
4. **Dynamic scaling**: Retrieval parameters adapt to document size rather than using fixed thresholds
5. **Transparent citations**: Every factual claim in the answer links back to its source chunk with page number and section title
6. **Streaming-first**: Users see answers as they are generated, not after a long wait
