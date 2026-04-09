from FlagEmbedding import BGEM3FlagModel
from app.core.config import get_settings
from app.utils.qdrant_client import hybrid_search
from app.services.llm_client import rewrite_query
from typing import List, Dict, Any, Tuple
from qdrant_client import models

_settings = get_settings()

_model: BGEM3FlagModel | None = None


def get_embedding_model() -> BGEM3FlagModel:
    global _model
    if _model is None:
        _model = BGEM3FlagModel(
            _settings.embedding_model_name,
            use_fp16=True,
            device="cuda"
        )
    return _model


def retrieve_chunks(
    document_id: str,
    query: str,
    use_rewrite: bool = True,
    limit: int = 80
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant chunks using hybrid search with optional multi-query expansion.

    Args:
        document_id: The document to search in
        query: The user query
        use_rewrite: Whether to rewrite the query first (generates multiple queries)
        limit: Maximum number of results per query

    Returns:
        Deduplicated list of retrieved chunks with scores
    """
    model = get_embedding_model()

    # Optionally rewrite query into multiple queries
    if use_rewrite:
        queries = rewrite_query(query)
    else:
        queries = [query]

    # Encode all queries
    query_embs = model.encode(
        queries,
        return_dense=True,
        return_sparse=True
    )

    # Retrieve for each query and merge by chunk_id (keep best score)
    seen: Dict[str, Dict[str, Any]] = {}

    for i in range(len(queries)):
        query_dense = query_embs['dense_vecs'][i].tolist()
        query_sparse = query_embs['lexical_weights'][i]

        results = hybrid_search(
            query_dense=query_dense,
            query_sparse=query_sparse,
            document_id=document_id,
            limit=limit
        )

        for point in results:
            cid = point.payload.get("chunk_id")
            if cid and cid not in seen:
                seen[cid] = {
                    "chunk_id": cid,
                    "score": point.score,
                    "page_start": point.payload.get("page_start"),
                    "page_end": point.payload.get("page_end"),
                    "content": point.payload.get("content"),
                    "section_title": point.payload.get("section_title"),
                }
            elif cid and point.score > seen[cid]["score"]:
                seen[cid]["score"] = point.score

    # Sort by score descending
    chunks = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return chunks


def bundle_chunks(chunks: List[Dict[str, Any]], max_gap: int = 1) -> List[Dict[str, Any]]:
    """
    Bundle consecutive chunks into larger context blocks.

    Args:
        chunks: List of retrieved chunks
        max_gap: Maximum page gap to consider consecutive

    Returns:
        List of bundled contexts
    """
    if not chunks:
        return []

    # Sort by page_start
    sorted_chunks = sorted(chunks, key=lambda x: x.get("page_start", 0))

    bundles = []
    current_bundle = [sorted_chunks[0]]

    for i in range(1, len(sorted_chunks)):
        prev_chunk = sorted_chunks[i - 1]
        curr_chunk = sorted_chunks[i]

        prev_page = prev_chunk.get("page_end", prev_chunk.get("page_start", 0))
        curr_page = curr_chunk.get("page_start", 0)

        # Check if consecutive
        if curr_page - prev_page <= max_gap:
            current_bundle.append(curr_chunk)
        else:
            # Save current bundle and start new one
            bundles.append(create_bundle(current_bundle))
            current_bundle = [curr_chunk]

    # Add last bundle
    if current_bundle:
        bundles.append(create_bundle(current_bundle))

    return bundles


def create_bundle(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a bundled context from multiple chunks."""
    if len(chunks) == 1:
        return chunks[0]

    # Combine content
    combined_content = "\n\n".join(
        f"[Page {c.get('page_start', '?')}]\n{c.get('content', '')}"
        for c in chunks
    )

    return {
        "chunk_ids": [c.get("chunk_id") for c in chunks],
        "page_start": min(c.get("page_start", float('inf')) for c in chunks),
        "page_end": max(c.get("page_end", 0) for c in chunks),
        "content": combined_content,
        "section_titles": list(set(c.get("section_title", "") for c in chunks if c.get("section_title"))),
        "scores": [c.get("score", 0) for c in chunks],
    }
