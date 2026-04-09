from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse
from app.core.config import get_settings
from typing import List, Dict, Any, Optional
import uuid
import hashlib

_settings = get_settings()

_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=_settings.qdrant_path)
    return _client


def init_collection():
    """Initialize the collection with dense and sparse vectors."""
    client = get_qdrant_client()

    try:
        client.get_collection(_settings.collection_name)
    except (UnexpectedResponse, ValueError):
        client.create_collection(
            collection_name=_settings.collection_name,
            vectors_config={
                "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams()
            }
        )


def chunk_id_to_uuid(chunk_id: str) -> str:
    """Convert chunk_id to a valid UUID using deterministic hashing."""
    # Use MD5 to create a deterministic UUID from chunk_id
    hash = hashlib.md5(chunk_id.encode()).hexdigest()
    return f"{hash[:8]}-{hash[8:12]}-{hash[12:16]}-{hash[16:20]}-{hash[20:32]}"


def upsert_chunks(
    document_id: str,
    chunks: List[Dict[str, Any]],
    dense_vectors: List[List[float]],
    sparse_weights: List[Dict[int, float]]
):
    """Upsert chunks with dense and sparse vectors."""
    client = get_qdrant_client()

    points = []
    for i, chunk in enumerate(chunks):
        original_chunk_id = chunk.get("chunk_id", str(uuid.uuid4()))
        # Convert to valid UUID format
        chunk_uuid = chunk_id_to_uuid(original_chunk_id)

        sparse_indices = list(sparse_weights[i].keys())
        sparse_values = list(sparse_weights[i].values())

        points.append(
            models.PointStruct(
                id=chunk_uuid,
                vector={
                    "dense": dense_vectors[i],
                    "sparse": models.SparseVector(
                        indices=list(map(int, sparse_indices)),
                        values=sparse_values
                    )
                },
                payload={
                    "document_id": document_id,
                    "chunk_id": original_chunk_id,
                    "chunk_index": chunk.get("chunk_index", i),
                    "section_id": chunk.get("section_id"),
                    "section_title": chunk.get("section_title"),
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "chunk_type": chunk.get("chunk_type"),
                    "content": chunk.get("content"),
                    "content_brief": chunk.get("content_brief"),
                    "period": chunk.get("period"),
                }
            )
        )

    client.upsert(collection_name=_settings.collection_name, points=points)


def hybrid_search(
    query_dense: List[float],
    query_sparse: Dict[int, float],
    document_id: str,
    limit: int = 80
) -> List[models.ScoredPoint]:
    """Perform hybrid search with RRF fusion."""
    client = get_qdrant_client()

    results = client.query_points(
        collection_name=_settings.collection_name,
        prefetch=[
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(map(int, query_sparse.keys())),
                    values=list(query_sparse.values())
                ),
                using="sparse",
                limit=limit,
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            models.Prefetch(
                query=query_dense,
                using="dense",
                limit=limit,
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True
    )

    return results.points


def get_chunk(document_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    """Get a single chunk by ID."""
    client = get_qdrant_client()

    try:
        result = client.retrieve(
            collection_name=_settings.collection_name,
            ids=[chunk_id],
            with_payload=True
        )
        if result:
            return result[0].payload
    except Exception:
        pass

    return None


def count_document_chunks(document_id: str) -> int:
    """Count total chunks for a document."""
    client = get_qdrant_client()
    try:
        result = client.count(
            collection_name=_settings.collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id)
                    )
                ]
            )
        )
        return result.count
    except Exception:
        return 0


def delete_document_chunks(document_id: str):
    """Delete all chunks for a document."""
    client = get_qdrant_client()

    client.delete(
        collection_name=_settings.collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=document_id)
                    )
                ]
            )
        )
    )
