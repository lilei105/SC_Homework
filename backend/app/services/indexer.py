from FlagEmbedding import BGEM3FlagModel
from app.core.config import get_settings
from app.utils.qdrant_client import upsert_chunks, init_collection
from app.models.schemas import DocumentSchema, ChunkData
from typing import List, Dict, Any
import json
import os

_settings = get_settings()

_model: BGEM3FlagModel | None = None


def get_embedding_model() -> BGEM3FlagModel:
    global _model
    if _model is None:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = BGEM3FlagModel(
            _settings.embedding_model_name,
            use_fp16=device == "cuda",
            device=device
        )
        print(f"Loaded embedding model on {device}")
    return _model


def augment_chunk_text(chunk: ChunkData, company_name: str) -> str:
    """Create augmented text for embedding."""
    parts = []

    # Add company name
    if company_name:
        parts.append(f"[{company_name}]")

    # Add period info
    if chunk.period:
        parts.append(f"[{chunk.period.date_label}]")

    # Add section title
    if chunk.section_title:
        parts.append(f"- {chunk.section_title}")

    # Add content brief if available
    if chunk.content_brief:
        parts.append(chunk.content_brief)

    # Add main content
    parts.append(chunk.content)

    return "\n".join(parts)


def index_document(document: DocumentSchema, status_callback=None) -> Dict[str, Any]:
    """
    Index a document into Qdrant.

    Args:
        document: The document schema with chunks
        status_callback: Optional callback for progress updates

    Returns:
        Dict with indexing results
    """
    init_collection()

    model = get_embedding_model()
    company_name = document.document.company_name
    chunks = document.chunks

    if not chunks:
        return {"indexed": 0, "error": "No chunks to index"}

    total_chunks = len(chunks)

    if status_callback:
        status_callback(total=total_chunks, indexed=0)

    # Prepare augmented texts
    augmented_texts = [augment_chunk_text(chunk, company_name) for chunk in chunks]

    # Encode in batches
    batch_size = 8
    all_dense_vecs = []
    all_lexical_weights = []

    for i in range(0, len(augmented_texts), batch_size):
        batch = augmented_texts[i:i + batch_size]
        embeddings = model.encode(
            batch,
            return_dense=True,
            return_sparse=True
        )
        all_dense_vecs.extend(embeddings['dense_vecs'])
        all_lexical_weights.extend(embeddings['lexical_weights'])

        if status_callback:
            status_callback(total=total_chunks, indexed=min(i + batch_size, total_chunks))

    # Convert to lists
    dense_vectors = [vec.tolist() if hasattr(vec, 'tolist') else vec for vec in all_dense_vecs]

    # Prepare chunk data
    chunk_dicts = []
    for i, chunk in enumerate(chunks):
        chunk_dict = {
            "chunk_id": chunk.chunk_id,
            "chunk_index": i,
            "section_id": chunk.section_id,
            "section_title": chunk.section_title,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chunk_type": chunk.chunk_type,
            "content": chunk.content,
            "content_brief": chunk.content_brief,
            "period": chunk.period.model_dump() if chunk.period else None,
        }
        chunk_dicts.append(chunk_dict)

    # Upsert to Qdrant
    upsert_chunks(
        document_id=document.document.document_id,
        chunks=chunk_dicts,
        dense_vectors=dense_vectors,
        sparse_weights=all_lexical_weights
    )

    return {"indexed": total_chunks}


def load_document_from_file(file_path: str) -> DocumentSchema:
    """Load document schema from JSON file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return DocumentSchema(**data)
