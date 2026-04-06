from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.models.schemas import DocumentStatus, DocumentSchema
from app.services.indexer import index_document
from typing import Dict, List, Optional
import json
import os
import logging
from datetime import datetime
from pathlib import Path

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

# In-memory storage for document status
_documents: Dict[str, dict] = {}
_document_status: Dict[str, DocumentStatus] = {}

# Persistence configuration
DATA_PATH = Path("./data")
PERSISTENCE_FILE = DATA_PATH / "document_status.json"


def _ensure_data_dir():
    """Ensure data directory exists."""
    os.makedirs(DATA_PATH, exist_ok=True)
    os.makedirs(DATA_PATH / "uploads", exist_ok=True)


def _save_persistence():
    """Save document status to disk."""
    _ensure_data_dir()
    data = {
        "documents": _documents,
        "document_status": {k: v.model_dump(mode='json') for k, v in _document_status.items()}
    }
    with open(PERSISTENCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_persistence():
    """Load document status from disk."""
    global _documents, _document_status
    if not PERSISTENCE_FILE.exists():
        return

    try:
        with open(PERSISTENCE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

        _documents = data.get("documents", {})
        status_data = data.get("document_status", {})

        for doc_id, status_dict in status_data.items():
            _document_status[doc_id] = DocumentStatus(**status_dict)

        logger.info(f"Restored {len(_documents)} documents from persistence")
    except Exception as e:
        logger.error(f"Failed to load persistence: {e}")


def _restore_from_qdrant():
    """Restore document metadata from Qdrant storage."""
    from app.utils.qdrant_client import get_qdrant_client
    from app.core.config import get_settings

    settings = get_settings()
    client = get_qdrant_client()

    try:
        collection = client.get_collection(settings.collection_name)
        if not collection:
            return

        # Scroll through all points to find unique document IDs
        doc_chunks: Dict[str, int] = {}
        offset = None

        while True:
            points, offset = client.scroll(
                collection_name=settings.collection_name,
                limit=100,
                offset=offset,
                with_payload=True
            )

            for point in points:
                doc_id = point.payload.get("document_id")
                if doc_id:
                    doc_chunks[doc_id] = doc_chunks.get(doc_id, 0) + 1

            if offset is None:
                break

        # Create status for each document
        for doc_id, chunk_count in doc_chunks.items():
            if doc_id not in _document_status:
                _document_status[doc_id] = DocumentStatus(
                    document_id=doc_id,
                    status="completed",
                    total_chunks=chunk_count,
                    indexed_chunks=chunk_count,
                    error=None,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                _documents[doc_id] = {"document_id": doc_id}

        logger.info(f"Restored {len(doc_chunks)} documents from Qdrant")
        _save_persistence()

    except Exception as e:
        logger.error(f"Failed to restore from Qdrant: {e}")


# Initialize on module load
_ensure_data_dir()
_load_persistence()
_restore_from_qdrant()


def get_document(document_id: str) -> Optional[dict]:
    """Get document by ID."""
    return _documents.get(document_id)


def get_document_status(document_id: str) -> Optional[DocumentStatus]:
    """Get document status by ID."""
    return _document_status.get(document_id)


def list_documents() -> List[dict]:
    """List all uploaded documents."""
    result = []
    for doc_id, status in _document_status.items():
        doc = _documents.get(doc_id, {})
        result.append({
            "document_id": doc_id,
            "source_file": doc.get("source_file"),
            "report_type": doc.get("report_type"),
            "report_title": doc.get("report_title"),
            "language": doc.get("language"),
            "currency": doc.get("currency"),
            "fiscal_year": doc.get("fiscal_year"),
            "fiscal_period": doc.get("fiscal_period"),
            "report_date": doc.get("report_date"),
            "page_count": doc.get("page_count"),
            "status": status.status,
            "indexed_chunks": status.indexed_chunks,
            "total_chunks": status.total_chunks
        })
    return result


def delete_document(document_id: str) -> bool:
    """Delete a document and all its chunks."""
    from app.utils.qdrant_client import get_qdrant_client
    from app.core.config import get_settings
    from qdrant_client import models

    settings = get_settings()
    client = get_qdrant_client()

    try:
        # Delete from Qdrant
        client.delete(
            collection_name=settings.collection_name,
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

        # Remove from memory and persistence
        if document_id in _documents:
            del _documents[document_id]
        if document_id in _document_status:
            del _document_status[document_id]

        _save_persistence()
        return True

    except Exception as e:
        logger.error(f"Failed to delete document {document_id}: {e}")
        return False


@router.post("")
async def upload_document(file: UploadFile = File(...)):
    """Upload and index a document."""
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Only JSON files are supported")

    _ensure_data_dir()

    # Read file content
    content = await file.read()
    try:
        doc_data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    # Get document ID (support both flat and nested formats)
    document_id = doc_data.get("document_id") or doc_data.get("document", {}).get("document_id")
    if not document_id:
        raise HTTPException(status_code=400, detail="Missing document_id in JSON")

    # Extract document metadata from nested structure if present
    doc_meta = doc_data.get("document", doc_data)

    # Save file
    file_path = DATA_PATH / "uploads" / f"{document_id}.json"
    with open(file_path, 'wb') as f:
        f.write(content)

    # Store document metadata
    _documents[document_id] = {
        "document_id": document_id,
        "source_file": file.filename,
        "report_type": doc_meta.get("report_type"),
        "report_title": doc_meta.get("report_title"),
        "language": doc_meta.get("language"),
        "currency": doc_meta.get("currency"),
        "fiscal_year": doc_meta.get("fiscal_year"),
        "fiscal_period": doc_meta.get("fiscal_period"),
        "report_date": doc_meta.get("report_date"),
        "page_count": doc_meta.get("page_count", len(doc_data.get("pages", [])))
    }

    # Create initial status
    _document_status[document_id] = DocumentStatus(
        document_id=document_id,
        status="indexing",
        total_chunks=0,
        indexed_chunks=0,
        error=None,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    _save_persistence()

    # Index document
    try:
        # Convert dict to DocumentSchema
        doc_schema = DocumentSchema(**doc_data)
        index_document(doc_schema)

        # Update status to completed
        _document_status[document_id].status = "completed"
        _document_status[document_id].updated_at = datetime.now().isoformat()
        _save_persistence()

    except Exception as e:
        logger.error(f"Failed to index document {document_id}: {e}")
        _document_status[document_id].status = "failed"
        _document_status[document_id].error = str(e)
        _document_status[document_id].updated_at = datetime.now().isoformat()
        _save_persistence()

    return {"document_id": document_id, "status": "indexing"}


@router.get("")
async def get_documents():
    """List all documents."""
    return list_documents()


@router.get("/{document_id}")
async def get_document_by_id(document_id: str):
    """Get document details."""
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    status = get_document_status(document_id)
    return {
        "document": doc,
        "status": status.model_dump() if status else None
    }


@router.get("/{document_id}/status")
async def get_status(document_id: str):
    """Get document indexing status."""
    status = get_document_status(document_id)
    if not status:
        raise HTTPException(status_code=404, detail="Document not found")
    return status


@router.delete("/{document_id}")
async def delete_document_endpoint(document_id: str):
    """Delete a document."""
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")

    success = delete_document(document_id)
    if success:
        return {"message": "Document deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete document")
