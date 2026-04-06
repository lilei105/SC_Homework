from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
from app.models.schemas import ChatRequest
from app.services.retriever import retrieve_chunks, bundle_chunks
from app.services.reranker import two_stage_rerank
from app.services.generator import generate_answer
from app.api.endpoints.documents import _documents, _document_status
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
            # 1. Retrieve chunks (disable query rewrite to avoid rate limiting)
            chunks = retrieve_chunks(document_id, query, use_rewrite=False)
            if not chunks:
                yield json.dumps({"type": "error", "message": "No relevant content found"})
                return

            # 2. Bundle consecutive chunks
            bundles = bundle_chunks(chunks)

            # 3. Two-stage reranking
            top_contexts = two_stage_rerank(query, bundles)

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
                            "page": cit["page"],
                            "chunk_id": cit["chunk_id"],
                            "content": cit["content"][:200] + "..." if cit.get("content") and len(cit["content"]) > 200 else cit.get("content")
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
