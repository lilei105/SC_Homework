# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Financial Report RAG (Retrieval-Augmented Generation) system design project. The repository contains planning documents for a homework assignment - no implementation code exists yet.

## Architecture Summary

The system follows a three-pipeline architecture based on FinSage and VeritasFi research papers:

1. **Indexing Pipeline**: Converts structured page data into multi-dimensional vector representations
   - Chunk-level metadata augmentation (using existing schema fields, no LLM calls needed)
   - BGE-M3 dual encoding (Dense + Sparse vectors)
   - Qdrant storage with named vectors

2. **Retrieval Pipeline**: Hybrid search with context recovery
   - Query rewriting via Zhipu LLM
   - Native hybrid retrieval (Dense + Sparse via Qdrant RRF)
   - Page-level chunk bundling for cross-page context

3. **Re-ranking & Generation Pipeline**: Precision ranking and answer generation
   - Two-stage reranking: ColBERT MaxSim (real-time) → Cross-Encoder (bge-reranker-v2-gemma)
   - Answer generation via Zhipu API with citation constraints

## Key Documents

| File | Purpose |
|------|---------|
| `prd.md` | Product requirements document (Chinese) - system design and module specifications |
| `coding_spec.md` | Technical implementation guide - project structure, code patterns, API design |
| `financial_report_rag_schema.jsonc` | JSON Schema for intermediate data format - document/section/chunk structure |

## Technical Stack (Planned)

- **Backend**: FastAPI (Python 3.11+)
- **Frontend**: React + TypeScript + TailwindCSS
- **Vector DB**: Qdrant (local file mode via `qdrant-client`)
- **Embedding**: `BAAI/bge-m3` (local, FlagEmbedding library)
- **Reranker**: `BAAI/bge-reranker-v2-gemma` (local)
- **LLM**: Zhipu `glm-4-flash` API

## Critical Design Decisions

- **No sliding window chunking**: Financial reports use page-level chunks (200-400 tokens average), avoiding table/logic fragmentation
- **No ColBERT persistence**: ColBERT vectors computed on-demand during reranking to save storage
- **No LLM for summaries**: Schema already provides `content_brief`, `section_summary` - just concatenate existing fields
- **Citation format**: Answers must include page citations like `[Page 25]`

## Language

All documentation is in Chinese. Code comments and variable names should follow the patterns established in `coding_spec.md`.
