# Financial Report RAG System - Product Requirements Document

## 1. Product Overview

### 1.1 Background
In financial scenarios, traditional RAG systems face significant challenges: financial reports contain dense numerical data, complex tables, and cross-page logical narratives; user queries often demand absolute precision (e.g., "Q3 2024 operating profit for a specific business segment"). Generic RAG architectures (single text chunking + dense vector retrieval) often suffer from context fragmentation, numerical matching failures, and severe hallucinations when processing such documents.

### 1.2 Design Basis
The core architecture of this system is deeply inspired by two papers focused on financial document processing: FinSage [1] and VeritasFi [2]. To meet rapid iteration requirements, this solution streamlines and optimizes complex modules from these papers, forming a "high-precision, easy-to-deploy" hybrid local and online architecture.

### 1.3 Core Assumptions
System input is pre-processed: documents have been parsed through OCR and layout analysis tools (such as MinerU or PaddleOCR-VL) and converted into page-structured JSON data. Each page serves as a complete, natural semantic unit (Chunk), with an average length of 200-400 tokens. Under this assumption, the system **does not require sliding window chunking with overlap**.

## 2. Core Module Design

### 2.1 Indexing Pipeline

The indexing pipeline transforms structured page data into vector representations supporting multi-dimensional high-precision retrieval.

#### 2.1.1 Chunk-level Metadata Augmentation
*   **Requirement**: Isolated financial values lack context. Each page must be enriched with macro semantic labels to improve global retrieval matching [1] [2].
*   **Implementation**:
    1.  Call LLM (such as Zhipu `glm-4.7-flash` API) with single-page structured text as input.
    2.  Model outputs standardized heading summary containing: company name, reporting period, page core topic (e.g., "Apple Inc. Q3 2024 - Revenue by Segment").
    3.  Use generated summary as metadata, directly prepended to the page's original text to form augmented text for encoding.

#### 2.1.2 BGE-M3 Native Dual-Path Encoding and Storage
*   **Requirement**: Financial queries need to understand both "semantics" (e.g., Profit vs Income) and precisely match "vocabulary" (e.g., EBITDA, $12.3B).
*   **Implementation**:
    1.  Load locally deployed `BAAI/bge-m3` model (via `FlagEmbedding` library).
    2.  Perform single forward pass on augmented text to obtain dense vectors and sparse lexical weights.
    3.  **Store to Qdrant**: Qdrant natively supports mounting multiple named vectors on a single record. Store 1024-dimensional dense vectors in `dense` field, vocabulary weight dictionaries in `sparse` field. This design avoids complexity of maintaining two independent indices, and Qdrant's Python client (`qdrant-client`) provides simple local single-file mode, ideal for rapid prototyping.

*   **Note: ColBERT Vector Processing Strategy**
    The third representation from BGE-M3 (ColBERT Multi-Vector) is a variable-length tensor that cannot be directly stored in conventional vector databases. Considering a financial report typically has 100-300 pages, pre-computing and storing ColBERT vectors for all pages not only increases storage overhead but also complicates engineering implementation. Therefore, this solution **does not persist ColBERT vectors**, but defers them to the re-ranking stage for **on-demand real-time computation** on a small number of candidate pages.

### 2.2 Retrieval Pipeline

The retrieval pipeline aims to precisely and comprehensively recall candidate pages relevant to user queries from massive pages, and restore complete financial logical chains.

#### 2.2.1 Query Rewrite
*   **Requirement**: User natural language queries are often colloquial and scattered in information, making direct retrieval ineffective.
*   **Implementation**: Call LLM (`glm-4.7-flash`) to parse intent and rewrite original query, extracting core entities (company, time, metrics) to generate standardized retrieval queries.

#### 2.2.2 Native Hybrid Preliminary Recall
*   **Requirement**: Combine dual advantages of semantic and lexical matching for preliminary candidate filtering.
*   **Implementation**:
    1.  Use BGE-M3 to encode rewritten query, obtaining query dense vectors and sparse weights.
    2.  Execute concurrent hybrid retrieval in Qdrant.
    3.  Dense path recalls Top-50 pages; Sparse path recalls Top-50 pages.
    4.  Merge and deduplicate both paths, generating a set of 50-80 candidate pages.

#### 2.2.3 Page-level Chunk Bundling
*   **Requirement**: Solve information fragmentation caused by cross-page financial narratives, restore document's original logical structure [1] [2].
*   **Implementation**:
    1.  Traverse page IDs (page numbers) in candidate set.
    2.  Detect consecutive page numbers (e.g., both page 10 and 11 are recalled).
    3.  If consecutive pages exist, concatenate them in memory in order to form a larger, semantically coherent composite context block.

### 2.3 Re-ranking & Generation Pipeline

This pipeline aims to perform ultimate precision ranking on candidate pages, and generate final financial analysis reports or precise answers based on most relevant context.

#### 2.3.1 Two-stage Fine Re-ranking
*   **Requirement**: Preliminary recall of 50-80 pages still contains significant noise, requiring deep semantic interaction for filtering.
*   **Implementation**:
    1.  **First-stage Re-ranking (ColBERT MaxSim Real-time Computation)**: Since candidate set is reduced to 50-80 pages, re-call BGE-M3 for these pages to extract ColBERT vectors, and compute token-level maximum similarity (Late Interaction) with query ColBERT vectors. This step takes hundreds of milliseconds, precisely reducing candidate set to Top-10.
    2.  **Second-stage Re-ranking (Cross-Encoder)**: Concatenate Top-10 pages with query, input to locally deployed `bge-reranker-v2-gemma` model for deep cross-scoring [1] [2]. Select Top-3 pages with highest scores as final context.

#### 2.3.2 Answer Generation
*   **Requirement**: Generate hallucination-free financial answers based on precise context.
*   **Implementation**:
    1.  Input Top-3 pages (approximately 600-1200 tokens) as context to Zhipu `glm-4.7-flash` API.
    2.  **Prompt Constraints**:
        *   Force model to answer only based on provided context, prohibiting internal knowledge usage.
        *   If answer involves specific numbers, must cite source page numbers in parentheses.
        *   Support generating structured executive summaries or specific metric comparisons based on user instructions.

## 3. Architecture Advantages Summary

This solution achieves perfect balance between academic depth and engineering feasibility within 2-3 day development cycle:
1.  **Eliminate ineffective chunking**: Confirms page-level semantic independence of financial reports, directly using pages as chunks, completely avoiding table destruction and logic truncation from sliding window chunking.
2.  **Elegant multi-path recall**: By introducing Qdrant, activates BGE-M3 model's native Dense+Sparse hybrid retrieval capability, avoiding architectural redundancy and performance degradation from external traditional BM25 libraries.
3.  **Deep context recovery**: Faithfully replicates Chunk Bundling and LLM-based cross re-ranking techniques from papers, through ColBERT on-demand real-time computation strategy ensuring extremely high ranking precision without increasing storage burden.

## References

[1] FinSage: A Multi-aspect RAG System for Financial Filings Question Answering (arXiv:2504.14493)
[2] VeritasFi: An Adaptable, Multi-tiered RAG Framework for Multi-modal Financial Question Answering (arXiv:2510.10828)
