# Financial Report RAG System

A production-ready Retrieval-Augmented Generation (RAG) system designed specifically for financial report Q&A. Built with FastAPI backend and React frontend, featuring multi-modal retrieval with hybrid search and two-stage reranking.

## 🎯 Key Features

- **PDF Upload & Processing**: Upload PDF reports directly, powered by Baidu PaddleOCR-VL for accurate document parsing
- **Intelligent Chunking**: LLM-based TOC extraction, section tree construction, and semantic chunking
- **Hybrid Retrieval**: Combines dense semantic vectors (BGE-M3) with sparse lexical matching
- **Two-Stage Reranking**: ColBERT MaxSim + Cross-Encoder for financial-grade accuracy
- **Streaming Responses**: Real-time SSE-based answer generation with page citations

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
│  │                     Indexing Pipeline (see below)                        │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                       Retrieval Pipeline                                 │ │
│  │  Query ──► Rewrite ──► BGE-M3 ──► Hybrid Search ──► Chunk Bundling    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    Reranking & Generation                                │ │
│  │  Candidates ──► ColBERT MaxSim ──► Cross-Encoder ──► LLM Generation    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📄 Document Processing Pipeline

The core of this system is the document processing pipeline that transforms raw PDF files into structured, searchable chunks. This section explains each stage in detail.

### Overview

```
PDF Upload
    │
    ▼
┌─────────────────┐
│  1. OCR Parse   │  ──► Baidu PaddleOCR-VL API
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Page Extract│  ──► {page_num: text} from JSON
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. TOC Extract │  ──► LLM extracts table of contents
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Section Tree│  ──► Build hierarchy, fill content
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Chunking    │  ──► Split sections into ~512 token chunks
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Embedding   │  ──► BGE-M3 Dense + Sparse vectors
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  7. Indexing    │  ──► Store to Qdrant
└─────────────────┘
```

### Stage 1: OCR Parsing

**Input**: Raw PDF file (up to 500 pages, 100MB)

**Process**: 
- Upload PDF to Baidu PaddleOCR-VL API
- API returns two URLs:
  - `markdown_url`: Full document as Markdown
  - `parse_result_url`: Structured JSON with page-level data

**Output**:
```json
{
  "file_name": "report.pdf",
  "pages": [
    {
      "page_num": 0,
      "text": "Full text content of page 1...",
      "layouts": [...],
      "tables": [...],
      "images": [...]
    },
    ...
  ]
}
```

**Why Baidu OCR?**
- Handles complex financial tables accurately
- Preserves document structure (headers, footers, page numbers)
- Supports 109 languages including mixed Chinese/English documents

### Stage 2: Page Extraction

**Input**: OCR JSON result

**Process**:
- Extract `pages[].text` from JSON
- Build `page_dict`: `{1: "page 1 text", 2: "page 2 text", ...}`
- Page numbers normalized to 1-indexed

**Output**:
```python
page_dict = {
    1: "HSBC Holdings plc\nAnnual Report 2024\n...",
    2: "Strategic Report\nPerformance Highlights\n...",
    ...
}
```

### Stage 3: TOC Extraction (LLM)

**Input**: First 5 pages of document

**Process**:
- Concatenate first 5 pages of content
- Call LLM (Qwen 3.5) with structured prompt
- LLM identifies section titles, page numbers, and hierarchy levels

**Prompt Template**:
```
You are a document structure extractor. Extract all sections and their page numbers.

Output JSON format:
{
  "sections": [
    {"title": "Strategic report", "level": 1},
    {"title": "Performance in 2024", "page": 1, "level": 2},
    {"title": "Highlights", "page": 2, "level": 2}
  ]
}

Rules:
- level 1 = Major sections (no page number)
- level 2 = Subsections (with page number)
- page is integer, null if uncertain
```

**Output**:
```json
{
  "sections": [
    {"title": "Strategic report", "level": 1},
    {"title": "Performance in 2024", "page": 1, "level": 2},
    {"title": "Highlights", "page": 2, "level": 2},
    {"title": "Financial review", "level": 1},
    {"title": "Financial summary", "page": 86, "level": 2}
  ]
}
```

### Stage 4: Section Tree Construction

**Input**: 
- TOC data (section titles and page numbers)
- page_dict (page content)

**Process**:
1. Determine page range for each section:
   - `page_start`: Section's TOC page number
   - `page_end`: Next section's page - 1 (or document end)

2. Extract content for each section:
   - Concatenate all pages in range
   - Calculate token count

3. Build two-level hierarchy:
   - Level 1 sections contain Level 2 children
   - Each Level 2 section has full content

**Output**:
```json
[
  {
    "title": "Strategic report",
    "level": 1,
    "page_start": 1,
    "page_end": 41,
    "tokens": 15000,
    "children": [
      {
        "title": "Performance in 2024",
        "level": 2,
        "page_start": 1,
        "page_end": 2,
        "tokens": 2500,
        "content": "Full text content..."
      },
      {
        "title": "Highlights",
        "level": 2,
        "page_start": 2,
        "page_end": 4,
        "tokens": 3200,
        "content": "Full text content..."
      }
    ]
  }
]
```

### Stage 5: Chunking

**Input**: Section tree with content

**Process**:

1. **Classify section type**:
   - `narrative`: Regular text sections
   - `table_heavy`: Multiple tables (≥3 table markers)
   - `kpi`: Key performance indicators
   - `mixed_media`: Contains images/figures
   - `risk_disclosure`: Risk-related sections
   - `appendix`: Supplementary material

2. **Split into chunks** (max 512 tokens each):
   - If section ≤ 512 tokens: Single chunk
   - If section > 512 tokens: Split by paragraphs
   - Preserve complete paragraphs where possible

3. **Enrich chunk metadata**:
   - `section_path`: `["Strategic report", "Highlights"]`
   - `page_start` / `page_end`: Source page range
   - `chunk_type`: Section classification

**Output**:
```json
[
  {
    "chunk_id": "chunk_0000",
    "chunk_index": 0,
    "section_path": ["Strategic report", "Performance in 2024"],
    "page_start": 1,
    "page_end": 2,
    "content": "HSBC Holdings plc reported strong...",
    "tokens": 450,
    "chunk_type": "narrative"
  },
  {
    "chunk_id": "chunk_0001",
    "chunk_index": 1,
    "section_path": ["Strategic report", "Highlights"],
    "page_start": 2,
    "page_end": 4,
    "content": "Key financial metrics for 2024...",
    "tokens": 512,
    "chunk_type": "kpi"
  }
]
```

### Stage 6: Embedding

**Input**: Chunks with content

**Process**:
1. **Metadata Augmentation**: Enhance chunk text with context
   ```
   [HSBC Holdings plc]
   [FY 2024]
   - Strategic report > Highlights
   
   Key financial metrics for 2024...
   ```

2. **BGE-M3 Encoding**: Single forward pass produces:
   - Dense vector: 1024 dimensions (semantic meaning)
   - Sparse weights: `{token: weight}` (lexical importance)

**Output**:
```python
{
    "dense": [0.023, -0.145, ...],  # 1024 floats
    "sparse": {"revenue": 0.82, "2024": 0.76, ...}
}
```

### Stage 7: Indexing to Qdrant

**Input**: Chunks with embeddings

**Process**:
- Store in Qdrant with named vectors:
  - `dense`: Cosine similarity search
  - `sparse`: BM25-style lexical search
- Payload includes: document_id, chunk_id, content, page info

**Storage Schema**:
```json
{
  "id": "chunk_0001",
  "vector": {
    "dense": [0.023, ...],
    "sparse": {"revenue": 0.82, ...}
  },
  "payload": {
    "document_id": "abc123",
    "chunk_id": "chunk_0001",
    "section_title": "Strategic report > Highlights",
    "page_start": 2,
    "page_end": 4,
    "content": "Key financial metrics..."
  }
}
```

---

## 📁 Processing Artifacts

Each document creates a task directory preserving all intermediate results:

```
data/tasks/{document_id}/
├── source.pdf          # Original uploaded file
├── ocr_result.md       # OCR markdown output
├── ocr_result.json     # Structured OCR result (pages, layouts, tables)
├── toc.json            # LLM-extracted table of contents
├── section_tree.json   # Section hierarchy with content
├── chunks_raw.json     # Chunks before embedding
├── document.json       # Final DocumentSchema
└── status.json         # Processing status log
```

This enables:
- Debugging retrieval issues
- Re-processing without re-OCR
- Auditing chunk boundaries

---

## 🔧 Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Backend** | FastAPI + Uvicorn | REST API server |
| **Frontend** | React + TypeScript + TailwindCSS | User interface |
| **Vector DB** | Qdrant (local file mode) | Dense + Sparse vector storage |
| **Embedding** | BAAI/bge-m3 | Multi-modal encoding |
| **Reranker** | BAAI/bge-reranker-v2-gemma | Cross-encoder reranking |
| **LLM** | Alibaba Qwen 3.5 | Query rewrite & generation |
| **OCR** | Baidu PaddleOCR-VL | PDF document parsing |

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- CUDA-capable GPU (recommended)

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

uvicorn app.main:app --reload
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Access at `http://localhost:5173`

---

## ⚙️ Configuration

```env
# backend/.env

# LLM API (Alibaba Dashscope)
DASHSCOPE_API_KEY=your_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.5-flash

# Baidu OCR API
BAIDU_OCR_API_KEY=your_key
BAIDU_OCR_SECRET_KEY=your_secret

# Storage
QDRANT_PATH=./data/qdrant_storage
COLLECTION_NAME=financial_reports

# Models
EMBEDDING_MODEL_NAME=BAAI/bge-m3
RERANKER_MODEL_NAME=BAAI/bge-reranker-v2-gemma
```

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/documents` | Upload PDF or JSON |
| `GET` | `/api/v1/documents` | List all documents |
| `GET` | `/api/v1/documents/{id}/status` | Get processing status |
| `DELETE` | `/api/v1/documents/{id}` | Delete document |
| `POST` | `/api/v1/chat` | Q&A (SSE streaming) |

---

## 📊 Document Status Flow

```
pending → parsing → chunking → indexing → completed
                                               ↓
                                             failed
```

| Status | Stage |
|--------|-------|
| `pending` | Uploaded, waiting |
| `parsing` | OCR in progress |
| `chunking` | TOC extraction, section building, splitting |
| `indexing` | Embedding and Qdrant storage |
| `completed` | Ready for Q&A |

---

## 🎓 Design Decisions

### Why Section-Based Chunking?

Unlike naive page-level or sliding-window chunking, our approach:

1. **Aggregate pages into semantic sections**: Use LLM-extracted TOC to group consecutive pages by topic
   - "Financial Highlights" spans pages 2-4 → Single section
   - Preserves cross-page tables and discussions

2. **Split within sections**: If a section exceeds 512 tokens, split by paragraph boundaries
   - Maintains semantic coherence
   - Avoids mid-sentence breaks

3. **Preserve hierarchy**: Each chunk knows its `section_path` (e.g., `["Strategic Report", "Financial Highlights"]`)

This approach prevents:
- Tables split across arbitrary page boundaries
- Related content scattered into unrelated chunks
- Loss of document structure in retrieval

### Why Hybrid Retrieval?

Financial queries need both:
- **Semantic matching**: "profit" ≈ "net income"
- **Exact matching**: "$12.3 billion", "Q3 2024", "EBITDA"

### Why Two-Stage Reranking?

| Stage | Input → Output | Purpose |
|-------|---------------|---------|
| ColBERT MaxSim | 50-80 → 10 | Token-level fine matching |
| Cross-Encoder | 10 → 3 | Deep semantic scoring |

---

## 📄 License

MIT License
