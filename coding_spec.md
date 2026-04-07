# Financial Report RAG System - Code Implementation Guide

This guide is based on `prd.md` and `financial_report_rag_schema.jsonc`, providing clear and executable engineering implementation instructions for Claude Code. The system adopts FastAPI + React frontend-backend architecture, with core retrieval and generation logic fully following the "high-precision, easy-to-deploy" hybrid local and online architecture defined in the PRD.

## 1. System Architecture & Technology Stack

To meet rapid iteration and local deployment requirements, the system adopts the following technology stack:

*   **Backend Framework**: FastAPI (Python 3.11+)
*   **Frontend Framework**: React + TypeScript + TailwindCSS (Vite build)
*   **Vector Database**: Qdrant (using `qdrant-client` local file mode, no separate server deployment required) [1]
*   **Core Models**:
    *   **Embedding & Sparse & ColBERT**: `BAAI/bge-m3` (running locally via `FlagEmbedding` library) [2]
    *   **Cross-Encoder Reranker**: `BAAI/bge-reranker-v2-gemma` (running locally via `FlagEmbedding` library) [3]
    *   **LLM (Summary & Generation)**: Zhipu `glm-4-flash` API (via `zhipuai` SDK) [4]

## 2. Project Directory Structure

To enable Claude Code to successfully build the project, the following directory structure is recommended:

```text
financial-rag/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── endpoints/
│   │   │   │   ├── documents.py    # Document upload and indexing API
│   │   │   │   └── chat.py         # Q&A interaction API
│   │   │   └── router.py           # Route registration
│   │   ├── core/
│   │   │   ├── config.py           # Environment variables and configuration management
│   │   │   └── prompts.py          # LLM Prompt templates centralized management
│   │   ├── models/
│   │   │   └── schemas.py          # Pydantic data models (based on JSON Schema)
│   │   ├── services/
│   │   │   ├── indexer.py          # Indexing pipeline logic
│   │   │   ├── retriever.py        # Retrieval pipeline logic
│   │   │   ├── reranker.py         # Re-ranking logic
│   │   │   ├── generator.py        # Answer generation logic
│   │   │   └── llm_client.py       # Zhipu API wrapper
│   │   ├── utils/
│   │   │   └── qdrant_client.py    # Qdrant client singleton wrapper
│   │   └── main.py                 # FastAPI application entry point
│   ├── data/                       # Local data storage (Qdrant data, uploaded JSON)
│   ├── requirements.txt            # Python dependencies
│   └── .env                        # Environment variables file (API Key, etc.)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── ChatBox.tsx     # Main chat interface
│   │   │   │   ├── Message.tsx     # Single message component (supports Markdown and Citation Badge)
│   │   │   │   └── InputArea.tsx   # Input area component
│   │   ├── Document/
│   │   │   │   ├── UploadModal.tsx # File upload modal
│   │   │   │   └── DocList.tsx     # Indexed document list
│   │   ├── Layout/
│   │   │   │   ├── Sidebar.tsx     # Sidebar (document management + session history)
│   │   │   │   └── Header.tsx      # Top navigation bar
│   │   ├── hooks/
│   │   │   └── useChat.ts          # Encapsulates SSE streaming request logic
│   │   ├── services/
│   │   │   └── api.ts              # Frontend API request wrapper
│   │   ├── types/
│   │   │   └── index.ts            # TypeScript type definitions
│   │   ├── App.tsx                 # Root component
│   │   └── main.tsx                # React entry point
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
└── README.md
```

## 3. Core Data Structure Design (Pydantic Models)

Backend needs to define strict Pydantic models based on provided JSON Schema to ensure type safety during data flow. Implement in `backend/app/models/schemas.py`:

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class PeriodInfo(BaseModel):
    fiscal_year: int
    fiscal_period: str
    date_label: str

class FinancialMetric(BaseModel):
    name: str
    value: str
    normalized_value: float
    unit: str
    period_label: str

class ChunkData(BaseModel):
    chunk_id: str
    chunk_index: int
    section_id: str
    section_title: str
    page_start: int
    page_end: int
    chunk_type: str
    content: str
    content_brief: Optional[str] = None
    keywords: List[str] = []
    period: Optional[PeriodInfo] = None
    financial_metrics: List[FinancialMetric] = []
    # Other fields according to Schema...

class DocumentSchema(BaseModel):
    document: Dict[str, Any]
    sections: List[Dict[str, Any]]
    chunks: List[ChunkData]
```

## 4. Core Module Implementation Guide

### 4.1 Indexing Pipeline

**Goal**: Parse JSON, call LLM for summary generation, use BGE-M3 to extract Dense and Sparse vectors, and store in Qdrant.

1.  **Qdrant Collection Initialization** (`backend/app/utils/qdrant_client.py`):
    Initialize collection using `qdrant-client` local mode, configure `dense` and `sparse` named vectors.

    ```python
    from qdrant_client import QdrantClient, models

    client = QdrantClient(path="./data/qdrant_storage")
    client.create_collection(
        collection_name="financial_reports",
        vectors_config={
            "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams()
        }
    )
    ```

2.  **Chunk-level Metadata Augmentation** (`backend/app/services/indexer.py`):
    Since upstream preprocessing already provides rich metadata in JSON Schema (such as `section_title`, `section_summary`, `content_brief`, `period`, etc.), the system **does not need to call LLM for summary generation**.
    Directly use existing fields in Schema for string concatenation to form high-density `augmented_text`.
    
    ```python
    augmented_texts = []
    for chunk in chunks:
        # Extract company name, report period, section title and chunk-level brief
        company = document_metadata.get("company_name", "")
        period_label = chunk.period.date_label if chunk.period else ""
        
        # Concatenation format: [Company] [Period] - [Section Title] \n [Chunk Brief] \n\n [Content]
        header = f"{company} {period_label} - {chunk.section_title}"
        brief = chunk.content_brief if chunk.content_brief else ""
        
        augmented_text = f"{header}\n{brief}\n\n{chunk.content}".strip()
        augmented_texts.append(augmented_text)
    ```

3.  **BGE-M3 Vector Extraction and Storage** (`backend/app/services/indexer.py`):
    Use `FlagEmbedding` to extract vectors. Note: **Do not store** ColBERT vectors here.

    ```python
    from FlagEmbedding import BGEM3FlagModel

    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

    # Extract Dense and Sparse
    embeddings = model.encode(augmented_texts, return_dense=True, return_sparse=True)
    dense_vecs = embeddings['dense_vecs']
    lexical_weights = embeddings['lexical_weights'] # List of dicts {token_id: weight}

    # Construct Qdrant PointStruct and insert
    points = []
    for i, chunk in enumerate(chunks):
        # Convert lexical_weights to Qdrant SparseVector format
        indices = list(lexical_weights[i].keys())
        values = list(lexical_weights[i].values())

        points.append(models.PointStruct(
            id=chunk.chunk_id, # Need to convert to UUID or integer
            vector={
                "dense": dense_vecs[i].tolist(),
                "sparse": models.SparseVector(indices=indices, values=values)
            },
            payload=chunk.model_dump() # Store complete Chunk data
        ))
    client.upsert(collection_name="financial_reports", points=points)
    ```

### 4.2 Retrieval Pipeline

**Goal**: Query rewriting, Qdrant hybrid retrieval, page-level chunk bundling.

1.  **Query Rewriting** (`backend/app/services/retriever.py`): Call Zhipu API to convert user Query to standardized retrieval terms.
2.  **Hybrid Search** (`backend/app/services/retriever.py`):
    Use Qdrant's Query API and Reciprocal Rank Fusion (RRF) for multi-path recall.

    ```python
    # 1. Extract vectors for rewritten Query
    query_emb = model.encode([rewritten_query], return_dense=True, return_sparse=True)
    q_dense = query_emb['dense_vecs'][0].tolist()
    q_sparse_dict = query_emb['lexical_weights'][0]

    # 2. Qdrant RRF hybrid retrieval
    results = client.query_points(
        collection_name="financial_reports",
        prefetch=[
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(q_sparse_dict.keys()),
                    values=list(q_sparse_dict.values())
                ),
                using="sparse",
                limit=50
            ),
            models.Prefetch(
                query=q_dense,
                using="dense",
                limit=50
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=80
    )
    ```

3.  **Page-level Chunk Bundling** (`backend/app/services/retriever.py`):
    Extract `payload` from `results`, sort by `page_start`. Detect consecutive page numbers, concatenate consecutive Chunks into a composite context block (Bundled Context).

### 4.3 Re-ranking & Generation Pipeline

**Goal**: ColBERT real-time computation, Cross-Encoder deep scoring, LLM final generation.

1.  **First-stage Re-ranking (ColBERT MaxSim)** (`backend/app/services/reranker.py`):
    Real-time compute ColBERT vectors for 50-80 Bundled Contexts obtained in previous step.

    ```python
    # Extract Query's ColBERT vector
    q_colbert = model.encode([rewritten_query], return_colbert_vecs=True)['colbert_vecs'][0]

    # Extract Contexts' ColBERT vectors and score
    ctx_colberts = model.encode(contexts, return_colbert_vecs=True)['colbert_vecs']

    scores = []
    for ctx_colbert in ctx_colberts:
        score = model.colbert_score(q_colbert, ctx_colbert)
        scores.append(score)

    # Filter Top-10 based on scores
    ```

2.  **Second-stage Re-ranking (Cross-Encoder)** (`backend/app/services/reranker.py`):
    Use `bge-reranker-v2-gemma` for ultimate precision ranking on Top-10.

    ```python
    from FlagEmbedding import FlagLLMReranker
    reranker = FlagLLMReranker('BAAI/bge-reranker-v2-gemma', use_fp16=True)

    pairs = [[rewritten_query, ctx] for ctx in top_10_contexts]
    rerank_scores = reranker.compute_score(pairs)

    # Select Top-3 as final context
    ```

3.  **Answer Generation** (`backend/app/services/generator.py`):
    Concatenate Top-3 contexts, build Prompt, call Zhipu API to generate final answer. Prompt must strictly constrain model to use only provided context, and require citing source page numbers (e.g., `[Page 25]`).

## 5. Core Prompt Template Design

Manage Prompts centrally in `backend/app/core/prompts.py`:

```python
QUERY_REWRITE_PROMPT = """
You are a professional financial analyst. Rewrite the user's natural language query into a standardized query suitable for vector retrieval.
Extract core entities (company, time period, metrics), and add relevant financial synonyms.

User query: {user_query}
Rewritten query:
"""

ANSWER_GENERATION_PROMPT = """
You are a rigorous financial report QA assistant. Answer the user's question strictly based on the provided context.

[Constraints]
1. Answer ONLY based on the provided context. Do NOT use internal knowledge.
2. If context does not contain enough information, clearly state "Based on provided documents, this question cannot be answered."
3. When referencing specific numbers or facts, cite source page numbers in format: [Page X].
4. Maintain objective, professional tone.

[Context]
{context}

[User Question]
{user_query}

[Answer]
"""
```

## 6. API Interface Design (FastAPI)

Backend needs to provide the following core RESTful APIs:

*   `POST /api/v1/documents`: Receive JSON file upload, trigger async Indexing Pipeline.
*   `GET /api/v1/documents`: Get list of indexed documents.
*   `POST /api/v1/chat`: Receive user Query, execute complete Retrieval -> Reranking -> Generation chain, support Server-Sent Events (SSE) streaming output.

## 7. Frontend Interaction Design (React)

Frontend interface should contain two main areas:

1.  **Document Management Area (Sidebar)**: Support uploading JSON files conforming to Schema, display processing status.
2.  **Q&A Interaction Area (Main Area)**:
    *   ChatGPT-like conversation interface.
    *   Support streaming typewriter effect for answer display.
    *   **Key Feature**: When answer contains citation page numbers (e.g., `[Page 25]`), frontend should render them as clickable Badges. On click, display corresponding original Chunk content (including table data) in sidebar or popup, to enhance explainability.

## 8. Deployment & Running Recommendations

*   **Environment Isolation**: Recommend using `uv` or `poetry` for Python dependency management.
*   **Model Download**: Before first startup, write script to pre-download `bge-m3` and `bge-reranker-v2-gemma` models from Hugging Face to local cache.
*   **Hardware Requirements**: Due to local LLM Reranker and BGE-M3, recommend running in GPU environment with at least 16GB VRAM (e.g., RTX 4080/4090 or A10G).

## References

[1] Qdrant Documentation: Hybrid Queries. https://qdrant.tech/documentation/search/hybrid-queries/
[2] BAAI/bge-m3 Model Card. https://huggingface.co/BAAI/bge-m3
[3] BAAI/bge-reranker-v2-gemma Model Card. https://huggingface.co/BAAI/bge-reranker-v2-gemma
[4] ZhipuAI Python SDK. https://github.com/MetaGLM/zhipuai-sdk-python-v4

---
*This document was automatically generated by Manus AI, specifically for providing architectural guidance for Claude Code engineering implementation.*
