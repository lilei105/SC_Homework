from FlagEmbedding import BGEM3FlagModel, FlagLLMReranker
from app.core.config import get_settings
from typing import List, Dict, Any, Tuple

_settings = get_settings()

_embedding_model: BGEM3FlagModel | None = None
_reranker: FlagLLMReranker | None = None


def get_embedding_model() -> BGEM3FlagModel:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = BGEM3FlagModel(
            _settings.embedding_model_name,
            use_fp16=True,
            device="cuda"
        )
    return _embedding_model


def get_reranker() -> FlagLLMReranker:
    global _reranker
    if _reranker is None:
        _reranker = FlagLLMReranker(
            _settings.reranker_model_name,
            use_fp16=True,
            device="cuda"
        )
    return _reranker


def colbert_rerank(
    query: str,
    contexts: List[Dict[str, Any]],
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    First-stage reranking using ColBERT MaxSim.

    Args:
        query: The user query
        contexts: List of context bundles
        top_k: Number of top results to return

    Returns:
        Top-k reranked contexts
    """
    if not contexts:
        return []

    model = get_embedding_model()

    # Get query ColBERT vectors
    query_emb = model.encode([query], return_colbert_vecs=True)
    query_colbert = query_emb['colbert_vecs'][0]

    # Get context ColBERT vectors
    context_texts = [c.get("content", "") for c in contexts]
    context_embs = model.encode(context_texts, return_colbert_vecs=True)
    context_colberts = context_embs['colbert_vecs']

    # Calculate MaxSim scores
    scores = []
    for i, ctx_colbert in enumerate(context_colberts):
        score = model.colbert_score(query_colbert, ctx_colbert)
        scores.append((i, float(score)))

    # Sort by score descending
    scores.sort(key=lambda x: x[1], reverse=True)

    # Return top_k
    return [contexts[i] | {"colbert_score": score} for i, score in scores[:top_k]]


def cross_encoder_rerank(
    query: str,
    contexts: List[Dict[str, Any]],
    top_k: int = 3
) -> List[Dict[str, Any]]:
    """
    Second-stage reranking using Cross-Encoder.

    Args:
        query: The user query
        contexts: List of contexts (should be pre-filtered by ColBERT)
        top_k: Number of top results to return

    Returns:
        Top-k reranked contexts with final scores
    """
    if not contexts:
        return []

    reranker = get_reranker()

    # Prepare pairs
    pairs = [[query, c.get("content", "")] for c in contexts]

    # Compute scores
    scores = reranker.compute_score(pairs, normalize=True)

    # Handle single result case
    if not isinstance(scores, list):
        scores = [scores]

    # Combine with contexts
    scored_contexts = [
        contexts[i] | {"rerank_score": float(scores[i])}
        for i in range(len(contexts))
    ]

    # Sort by score descending
    scored_contexts.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

    return scored_contexts[:top_k]


def two_stage_rerank(
    query: str,
    contexts: List[Dict[str, Any]],
    colbert_top_k: int = 20,
    final_top_k: int = 7
) -> List[Dict[str, Any]]:
    """
    Two-stage reranking: ColBERT -> Cross-Encoder.

    Args:
        query: The user query
        contexts: List of retrieved contexts
        colbert_top_k: Number of candidates after ColBERT
        final_top_k: Number of final results

    Returns:
        Final top-k contexts
    """
    # Stage 1: ColBERT
    colbert_results = colbert_rerank(query, contexts, top_k=colbert_top_k)

    # Stage 2: Cross-Encoder
    final_results = cross_encoder_rerank(query, colbert_results, top_k=final_top_k)

    return final_results
