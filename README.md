# Financial Report RAG System

A production-ready Retrieval-Augmented Generation (RAG) system designed specifically for financial report Q&A. Built with FastAPI backend and React frontend, featuring multi-modal retrieval with hybrid search and two-stage reranking.

## 🎯 Key Features

- **PDF Upload & Processing**: Upload PDF reports directly, powered by Baidu PaddleOCR-VL for accurate document parsing
- **Hybrid Retrieval**: Combines dense semantic vectors (BGE-M3) with sparse lexical matching for precise recall
- **Two-Stage Reranking**: ColBERT MaxSim + Cross-Encoder for financial-grade accuracy
- **Streaming Responses**: Real-time SSE-based answer generation
- **Citation Support**: Page-level citations in responses for traceability

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Frontend (React)                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Upload Modal│  │  Doc List   │  │  Chat Box   │  │  Status Polling     │ │
│  │ PDF / JSON  │  │  Sidebar    │  │  SSE Stream │  │  parsing→indexing   │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Backend (FastAPI)                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        Indexing Pipeline                                 │ │
│  │  PDF ──► Baidu OCR ──► TOC Extraction ──► Section Tree ──► Chunks     │ │
│  │                                    (LLM)           (LLM)                 │ │
│  │                                                                          │ │
│  │                      ┌──────────────────────────────┐                   │ │
│  │                      │     BGE-M3 Encoding          │                   │ │
│  │                      │  Dense Vector + Sparse Weights│                   │ │
│  │                      └──────────────────────────────┘                   │ │
│  │                                 │                                        │ │
│  │                                 ▼                                        │ │
│  │                      ┌──────────────────────────────┐                   │ │
│  │                      │     Qdrant Storage           │                   │ │
│  │                      │  Named Vectors (dense/sparse)│                   │ │
│  │                      └──────────────────────────────┘                   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                       Retrieval Pipeline                                 │ │
│  │                                                                          │ │
│  │  Query ──► Query Rewrite ──► BGE-M3 Encode ──► Hybrid Search          │ │
│  │              (LLM)              │                   │                    │ │
│  │                                 │                   ▼                    │ │
│  │                                 │         ┌──────────────────┐          │ │
│  │                                 │         │  RRF Fusion      │          │ │
│  │                                 │         │  Top 50-80 Docs  │          │ │
│  │                                 │         └──────────────────┘          │ │
│  │                                 │                   │                    │ │
│  │                                 ▼                   ▼                    │ │
│  │                          Chunk Bundling ◄──────────┘                    │ │
│  │                        (Consecutive Pages)                               │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    Reranking & Generation                                │ │
│  │                                                                          │ │
│  │  Candidates ──► ColBERT MaxSim ──► Cross-Encoder ──► Top-3 Context    │ │
│  │                   (Top-10)           (Top-3)                             │ │
│  │                                                            │             │ │
│  │                                                            ▼             │ │
│  │                                                   ┌──────────────────┐   │ │
│  │                                                   │  LLM Generation  │   │ │
│  │                                                   │  Stream via SSE  │   │ │
│  │                                                   └──────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🔧 Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend** | FastAPI + Uvicorn | REST API server |
| **Frontend** | React + TypeScript + TailwindCSS | User interface |
| **Vector DB** | Qdrant (local file mode) | Dense + Sparse vector storage |
| **Embedding** | BAAI/bge-m3 | Multi-modal encoding (Dense + Sparse + ColBERT) |
| **Reranker** | BAAI/bge-reranker-v2-gemma | Cross-encoder reranking |
| **LLM** | Alibaba Qwen 3.5 (via Dashscope API) | Query rewrite & answer generation |
| **OCR** | Baidu PaddleOCR-VL | PDF document parsing |

## 📁 Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py              # Route registration
│   │   │   └── endpoints/
│   │   │       ├── documents.py       # Document upload & management
│   │   │       └── chat.py            # Q&A streaming endpoint
│   │   ├── core/
│   │   │   ├── config.py              # Environment configuration
│   │   │   └── prompts.py             # LLM prompt templates
│   │   ├── models/
│   │   │   └── schemas.py             # Pydantic data models
│   │   ├── services/
│   │   │   ├── baidu_ocr.py           # Baidu OCR API integration
│   │   │   ├── chunker.py             # Document chunking service
│   │   │   ├── indexer.py             # Vector indexing pipeline
│   │   │   ├── retriever.py           # Hybrid retrieval
│   │   │   ├── reranker.py            # Two-stage reranking
│   │   │   ├── generator.py           # Answer generation
│   │   │   └── llm_client.py         # LLM API client
│   │   ├── utils/
│   │   │   └── qdrant_client.py      # Qdrant singleton
│   │   └── main.py                    # FastAPI entry point
│   ├── data/
│   │   ├── tasks/{document_id}/       # Per-document processing artifacts
│   │   │   ├── source.pdf             # Original uploaded PDF
│   │   │   ├── ocr_result.md         # OCR markdown output
│   │   │   ├── ocr_result.json       # OCR structured result (with pages)
│   │   │   ├── toc.json               # Extracted table of contents
│   │   │   ├── section_tree.json      # Built section hierarchy
│   │   │   ├── chunks_raw.json        # Raw chunks before indexing
│   │   │   ├── document.json          # Final DocumentSchema
│   │   │   └── status.json            # Processing status log
│   │   ├── qdrant_storage/            # Vector database
│   │   └── document_status.json       # Global document registry
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── Chat/
│       │   │   ├── ChatBox.tsx        # Main chat interface
│       │   │   ├── Message.tsx        # Message with citations
│       │   │   └── InputArea.tsx      # Query input
│       │   ├── Document/
│       │   │   ├── UploadModal.tsx    # PDF/JSON upload
│       │   │   └── DocList.tsx        # Document sidebar
│       │   └── Layout/
│       │       ├── Sidebar.tsx        # Navigation & status polling
│       │       └── Header.tsx         # Top bar
│       ├── hooks/
│       │   └── useChat.ts             # SSE streaming hook
│       ├── services/
│       │   └── api.ts                 # API client
│       └── types/
│           └── index.ts               # TypeScript interfaces
│
├── prd.md                             # Product requirements (Chinese)
├── coding_spec.md                     # Technical specifications
└── financial_report_rag_schema.jsonc  # Document schema definition
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- CUDA-capable GPU (recommended for local embedding)

### 1. Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
```

### 3. Run the Application

```bash
# Terminal 1: Backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0

# Terminal 2: Frontend
cd frontend
npm run dev
```

Access the application at `http://localhost:5173`

## ⚙️ Configuration

Create `backend/.env` with the following:

```env
# Alibaba Dashscope API (for LLM)
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-flash

# Baidu OCR API
BAIDU_OCR_API_KEY=your_api_key
BAIDU_OCR_SECRET_KEY=your_secret_key

# Qdrant
QDRANT_PATH=./data/qdrant_storage
COLLECTION_NAME=financial_reports

# Models
EMBEDDING_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-gemma
LLM_MODEL=qwen3.5-flash

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=True
```

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/documents` | Upload PDF or JSON document |
| `GET` | `/api/v1/documents` | List all documents |
| `GET` | `/api/v1/documents/{id}` | Get document details |
| `GET` | `/api/v1/documents/{id}/status` | Get processing status |
| `DELETE` | `/api/v1/documents/{id}` | Delete document |
| `POST` | `/api/v1/chat` | Q&A streaming (SSE) |

### Upload Document

```bash
# Upload PDF
curl -X POST "http://localhost:8000/api/v1/documents" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@report.pdf"

# Upload JSON (pre-processed)
curl -X POST "http://localhost:8000/api/v1/documents" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@document.json"
```

### Chat Query (SSE)

```javascript
const eventSource = new EventSource(
  '/api/v1/chat?document_id=xxx&query=What is the revenue in 2024?'
);

eventSource.onmessage = (event) => {
  console.log(event.data); // Streaming response
};
```

## 📊 Processing Pipeline

### Document Status Flow

```
pending → parsing → chunking → indexing → completed
                                               ↓
                                             failed
```

| Status | Description |
|--------|-------------|
| `pending` | Uploaded, waiting to process |
| `parsing` | OCR recognition in progress |
| `chunking` | Building section tree and splitting |
| `indexing` | Embedding and storing vectors |
| `completed` | Ready for Q&A |
| `failed` | Processing error |

### Processing Artifacts

Each uploaded document creates a task directory with all intermediate results:

```
data/tasks/{document_id}/
├── source.pdf          # Original file
├── ocr_result.md       # OCR markdown (for debugging)
├── ocr_result.json     # Structured OCR result with page info
├── toc.json            # LLM-extracted table of contents
├── section_tree.json   # Section hierarchy with content
├── chunks_raw.json     # Chunks before embedding
├── document.json       # Final DocumentSchema
└── status.json         # Processing log
```

## 🎓 Design Principles

### Why Not Sliding Window Chunking?

Financial reports have natural semantic boundaries at the page level (200-400 tokens average). Unlike general documents, sliding window chunking would:

- Split tables across chunks, breaking numerical context
- Fragment cross-page financial discussions
- Create redundant storage without improving retrieval

### Why Store Both Dense and Sparse Vectors?

Financial queries have dual requirements:

1. **Semantic understanding**: "profit margin" ≈ "net income ratio"
2. **Exact term matching**: "$12.3 billion", "EBITDA", "Q3 2024"

BGE-M3 provides both in a single forward pass, and Qdrant's RRF fusion combines them optimally.

### Why Two-Stage Reranking?

| Stage | Method | Input | Output | Latency |
|-------|--------|-------|--------|---------|
| 1 | ColBERT MaxSim | 50-80 candidates | Top-10 | ~100ms |
| 2 | Cross-Encoder | Top-10 | Top-3 | ~200ms |

ColBERT's late interaction captures fine-grained token matching, while Cross-Encoder provides deep semantic scoring. This combination achieves financial-grade precision.

## 📚 References

This system design is informed by:

1. **FinSage** - A Financial RAG System with Multi-Source Data and Multi-Stage Retrieval
2. **VeritasFi** - Financial RAG with Domain-Specific Chunking and Reranking

## 📄 License

MIT License
