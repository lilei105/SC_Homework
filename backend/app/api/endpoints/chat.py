from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
from app.models.schemas import ChatRequest
from app.services.retriever import retrieve_chunks
from app.services.reranker import two_stage_rerank
from app.services.generator import generate_answer
from app.api.endpoints.documents import _documents, _document_status
from app.utils.qdrant_client import count_document_chunks
import json
import asyncio

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("")
async def chat_stream(
    document_id: str = Query(...),
    query: str = Query(...)
):
    """Stream chat response with SSE."""
    # Validate document
    if document_id not in _documents:
        async def error_gen():
            yield json.dumps({"type": "error", "message": "Document not found"})
        return EventSourceResponse(error_gen())

    status = _document_status.get(document_id)
    if not status or status.status != "completed":
        async def error_gen():
            yield json.dumps({"type": "error", "message": "Document not ready"})
        return EventSourceResponse(error_gen())

    async def event_generator():
        try:
            # Dynamic retrieval/reranking params based on document size
            total_chunks = count_document_chunks(document_id)
            retrieve_limit = min(300, max(80, total_chunks // 5))
            colbert_top_k = min(50, max(20, retrieve_limit // 3))
            final_top_k = min(15, max(7, colbert_top_k // 3))

            # 1. Retrieve chunks with query rewriting
            chunks = retrieve_chunks(document_id, query, use_rewrite=True, limit=retrieve_limit)
            if not chunks:
                yield json.dumps({"type": "error", "message": "No relevant content found"})
                return

            # 2. Two-stage reranking on individual chunks
            top_contexts = two_stage_rerank(query, chunks, colbert_top_k=colbert_top_k, final_top_k=final_top_k)

            if not top_contexts:
                yield json.dumps({"type": "error", "message": "No relevant content after reranking"})
                return

            # 4. Stream answer generation
            citations = []
            for token, new_citations in generate_answer(query, top_contexts):
                # Send token
                yield json.dumps({"type": "token", "content": token})

                # Send new citations
                for cit in new_citations:
                    if cit not in citations:
                        citations.append(cit)
                        yield json.dumps({
                            "type": "citation",
                            "source_num": cit["source_num"],
                            "page_label": cit.get("page_label", ""),
                            "page_start": cit.get("page_start"),
                            "page_end": cit.get("page_end"),
                            "chunk_id": cit.get("chunk_id"),
                            "content": cit.get("content", ""),
                            "section_title": cit.get("section_title", ""),
                        })

                # Small delay for smoother streaming
                await asyncio.sleep(0.01)

            # Send done
            yield json.dumps({"type": "done"})

        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)})

    return EventSourceResponse(event_generator())


@router.post("")
async def chat_post(request: ChatRequest):
    """POST endpoint for chat (also uses SSE)."""
    # Redirect to GET endpoint
    return await chat_stream(request.document_id, request.query)
