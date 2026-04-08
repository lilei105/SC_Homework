from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from app.models.schemas import DocumentStatus, DocumentSchema
from app.services.indexer import index_document
from typing import Dict, List, Optional, Any
import json
import os
import logging
import uuid
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
    os.makedirs(DATA_PATH / "tasks", exist_ok=True)


def _get_task_dir(document_id: str) -> Path:
    """Get task directory for a document."""
    task_dir = DATA_PATH / "tasks" / document_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


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
                    file_type="json",
                    total_chunks=chunk_count,
                    indexed_chunks=chunk_count,
                    error=None,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                _documents[doc_id] = {"document_id": doc_id}

        logger.info(f"Restored {len(doc_chunks)} documents from Qdrant")
        _save_persistence()

    except Exception as e:
        logger.error(f"Failed to restore from Qdrant: {e}")


def _update_status(
    document_id: str,
    status: str,
    processing_stage: Optional[str] = None,
    error: Optional[str] = None,
    **kwargs
):
    """Update document status."""
    if document_id in _document_status:
        _document_status[document_id].status = status
        _document_status[document_id].updated_at = datetime.now()

        if processing_stage is not None:
            _document_status[document_id].processing_stage = processing_stage
        if error is not None:
            _document_status[document_id].error = error

        for key, value in kwargs.items():
            if hasattr(_document_status[document_id], key):
                setattr(_document_status[document_id], key, value)

        _save_persistence()


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
            "source_file": doc.get("source_file") or status.source_file,
            "report_type": doc.get("report_type"),
            "report_title": doc.get("report_title"),
            "language": doc.get("language"),
            "currency": doc.get("currency"),
            "fiscal_year": doc.get("fiscal_year"),
            "fiscal_period": doc.get("fiscal_period"),
            "report_date": doc.get("report_date"),
            "page_count": doc.get("page_count"),
            "status": status.status,
            "file_type": status.file_type,
            "processing_stage": status.processing_stage,
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


def _extract_from_paddleocr_json(ocr_json: list) -> tuple[str, dict]:
    """
    从 PaddleOCR-VL JSON 中提取 markdown 内容和页面字典

    Args:
        ocr_json: PaddleOCR-VL 返回的 JSON 列表

    Returns:
        (markdown_content, page_dict)
    """
    markdown_parts = []
    page_dict = {}

    for i, page_data in enumerate(ocr_json):
        page_num = i + 1
        pruned = page_data.get("prunedResult", {})

        # 优先使用 markdown 字段
        page_markdown = pruned.get("markdown", "")

        if not page_markdown:
            # 如果没有 markdown，从 parsing_res_list 构建
            blocks = pruned.get("parsing_res_list", [])
            block_contents = []
            for block in blocks:
                content = block.get("block_content", "")
                if content:
                    block_contents.append(content)
            page_markdown = "\n\n".join(block_contents)

        if page_markdown.strip():
            markdown_parts.append(f"<!-- PAGE: {page_num} -->\n{page_markdown.strip()}")
            page_dict[page_num] = page_markdown.strip()

    return "\n\n".join(markdown_parts), page_dict


def _is_paddleocr_format(data: Any) -> bool:
    """检测是否为 PaddleOCR-VL 格式的 JSON"""
    if not isinstance(data, list):
        return False
    if len(data) == 0:
        return False
    first = data[0]
    if not isinstance(first, dict):
        return False
    # PaddleOCR-VL 格式特征：有 prunedResult 字段
    return "prunedResult" in first or "parsing_res_list" in first


async def _process_and_index_document(
    document_id: str,
    markdown_content: str,
    ocr_json_result: dict,
    source_file: str,
    task_dir: Path
):
    """
    核心处理逻辑：Chunk -> Index

    PDF 和 PaddleOCR JSON 共享此流程
    """
    try:
        logger.info(f"[PROCESS] Starting chunk+index for {document_id}")

        # Update status: chunking
        _update_status(document_id, "chunking", "Chunking document...")

        # 2. Chunk document
        from app.services.chunker import get_chunker
        chunker = get_chunker()

        metadata = _documents.get(document_id, {})
        doc_schema, intermediate = chunker.process_markdown(
            markdown_content,
            {
                "document_id": document_id,
                "source_file": source_file,
                "company_name": metadata.get("company_name", "Unknown"),
                "report_type": metadata.get("report_type", "annual_report"),
                "report_title": metadata.get("report_title", ""),
                "language": metadata.get("language", "en"),
                "currency": metadata.get("currency", "USD"),
                "fiscal_year": metadata.get("fiscal_year", 2025),
                "fiscal_period": metadata.get("fiscal_period", "FY"),
            },
            ocr_json_result=ocr_json_result,
            save_intermediate=task_dir
        )

        # Save final document schema
        schema_path = task_dir / "document.json"
        schema_path.write_text(
            doc_schema.model_dump_json(indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved document schema to: {schema_path}")

        # Update document metadata
        _documents[document_id].update({
            "report_type": doc_schema.document.report_type,
            "report_title": doc_schema.document.report_title,
            "language": doc_schema.document.language,
            "currency": doc_schema.document.currency,
            "fiscal_year": doc_schema.document.fiscal_year,
            "fiscal_period": doc_schema.document.fiscal_period,
            "report_date": doc_schema.document.report_date,
            "page_count": doc_schema.document.page_count,
            "task_dir": str(task_dir.relative_to(DATA_PATH)),
        })

        # Save task status
        task_status_path = task_dir / "status.json"
        task_status = {
            "document_id": document_id,
            "status": "indexing",
            "source_file": source_file,
            "chunks": len(doc_schema.chunks),
            "pages": doc_schema.document.page_count,
            "updated_at": datetime.now().isoformat(),
        }
        task_status_path.write_text(
            json.dumps(task_status, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # Update status: indexing
        _update_status(
            document_id,
            "indexing",
            "Indexing...",
            total_chunks=len(doc_schema.chunks)
        )

        # 3. Index document
        index_document(doc_schema)

        # Update status: completed
        _update_status(
            document_id,
            "completed",
            None,
            indexed_chunks=len(doc_schema.chunks)
        )

        # Update task status file
        task_status["status"] = "completed"
        task_status["updated_at"] = datetime.now().isoformat()
        task_status_path.write_text(
            json.dumps(task_status, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        logger.info(f"Successfully processed document: {document_id}")

    except Exception as e:
        logger.error(f"Failed to process document {document_id}: {e}", exc_info=True)
        _update_status(document_id, "failed", None, str(e))


async def process_pdf_document(document_id: str, file_path: Path):
    """
    Background task: Process PDF document.

    Flow: OCR -> Chunk -> Index
    """
    task_dir = _get_task_dir(document_id)

    try:
        logger.info(f"Processing PDF document: {document_id}")

        # Update status: parsing
        _update_status(document_id, "parsing", "OCR processing...")

        # 1. OCR processing
        from app.services.baidu_ocr import get_ocr_service
        ocr_service = get_ocr_service()

        markdown_content, ocr_json_result = await ocr_service.process_pdf(file_path)

        # Save OCR results
        ocr_md_path = task_dir / "ocr_result.md"
        ocr_md_path.write_text(markdown_content, encoding="utf-8")

        ocr_json_path = task_dir / "ocr_result.json"
        ocr_json_path.write_text(
            json.dumps(ocr_json_result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        logger.info(f"Saved OCR results to: {task_dir}")

        # 2. Chunk & Index (共享逻辑)
        await _process_and_index_document(
            document_id=document_id,
            markdown_content=markdown_content,
            ocr_json_result=ocr_json_result,
            source_file=file_path.name,
            task_dir=task_dir
        )

    except Exception as e:
        logger.error(f"Failed to process PDF {document_id}: {e}", exc_info=True)
        _update_status(document_id, "failed", None, str(e))


def _run_sync_processing(document_id: str, ocr_json: list, source_file: str):
    """
    同步处理逻辑，在后台执行
    """
    logger.info(f"Processing: {document_id}")
    task_dir = _get_task_dir(document_id)

    try:
        # Save original JSON
        ocr_json_path = task_dir / "ocr_result.json"
        ocr_json_path.write_text(
            json.dumps(ocr_json, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        # 1. 从 JSON 提取 markdown 和页面信息
        markdown_content, page_dict = _extract_from_paddleocr_json(ocr_json)

        # Save markdown
        ocr_md_path = task_dir / "ocr_result.md"
        ocr_md_path.write_text(markdown_content, encoding="utf-8")

        # 转换为 chunker 期望的格式
        ocr_json_result = {
            "pages": [
                {"page_num": k - 1, "text": v}
                for k, v in page_dict.items()
            ]
        }

        # 2. Chunk & Index
        _process_and_index_sync(document_id, markdown_content, ocr_json_result, source_file, task_dir)

    except Exception as e:
        logger.error(f"Failed to process {document_id}: {e}", exc_info=True)
        _update_status(document_id, "failed", None, str(e))


def _process_and_index_sync(
    document_id: str,
    markdown_content: str,
    ocr_json_result: dict,
    source_file: str,
    task_dir: Path
):
    """
    同步版本的核心处理逻辑
    """
    try:
        # Update status: chunking
        _update_status(document_id, "chunking", "Chunking document...")

        # Chunk document
        from app.services.chunker import get_chunker
        chunker = get_chunker()

        metadata = _documents.get(document_id, {})
        doc_schema, intermediate = chunker.process_markdown(
            markdown_content,
            {
                "document_id": document_id,
                "source_file": source_file,
                "company_name": metadata.get("company_name", "Unknown"),
                "report_type": metadata.get("report_type", "annual_report"),
                "report_title": metadata.get("report_title", ""),
                "language": metadata.get("language", "en"),
                "currency": metadata.get("currency", "USD"),
                "fiscal_year": metadata.get("fiscal_year", 2025),
                "fiscal_period": metadata.get("fiscal_period", "FY"),
            },
            ocr_json_result=ocr_json_result,
            save_intermediate=task_dir
        )

        # Save final document schema
        schema_path = task_dir / "document.json"
        schema_path.write_text(
            doc_schema.model_dump_json(indent=2),
            encoding="utf-8"
        )

        # Update document metadata
        _documents[document_id].update({
            "report_type": doc_schema.document.report_type,
            "report_title": doc_schema.document.report_title,
            "language": doc_schema.document.language,
            "currency": doc_schema.document.currency,
            "fiscal_year": doc_schema.document.fiscal_year,
            "fiscal_period": doc_schema.document.fiscal_period,
            "report_date": doc_schema.document.report_date,
            "page_count": doc_schema.document.page_count,
            "task_dir": str(task_dir.relative_to(DATA_PATH)),
        })

        # Update status: indexing
        _update_status(
            document_id,
            "indexing",
            "Indexing...",
            total_chunks=len(doc_schema.chunks)
        )

        # Index document
        index_document(doc_schema)

        # Update status: enriching (background metadata extraction)
        _update_status(
            document_id,
            "enriching",
            "Extracting metadata...",
        )

        # Start background metadata enrichment (disabled for speed)
        # enrich_chunk_metadata_task(document_id, doc_schema.chunks)

        # Mark as completed directly
        _update_status(document_id, "completed", None, indexed_chunks=len(doc_schema.chunks))

        logger.info(f"Indexed: {document_id} ({len(doc_schema.chunks)} chunks), starting metadata enrichment")

    except Exception as e:
        logger.error(f"Failed: {document_id}: {e}", exc_info=True)
        _update_status(document_id, "failed", None, str(e))


def enrich_chunk_metadata_task(document_id: str, chunks: List):
    """
    Background task: Extract and update chunk metadata using LLM.

    This runs after indexing to enrich chunks with:
    - keywords
    - entities (companies, products, regions, people)
    - period information
    - financial metrics
    """
    from app.services.metadata_extractor import get_metadata_extractor
    from app.services.indexer import update_chunks_metadata_batch

    logger.info(f"[ENRICH] Starting metadata enrichment for {document_id} ({len(chunks)} chunks)")

    try:
        extractor = get_metadata_extractor()

        # Process in batches of 5 to avoid overwhelming the LLM
        batch_size = 5
        all_metadata_updates = []

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]

            for chunk in batch:
                try:
                    metadata = extractor.extract_chunk_metadata(
                        content=chunk.content,
                        section_title=chunk.section_title
                    )

                    all_metadata_updates.append({
                        "chunk_id": chunk.chunk_id,
                        "metadata": {
                            "keywords": metadata.get("keywords", []),
                            "entities": metadata.get("entities"),
                            "period": metadata.get("period"),
                            "financial_metrics": metadata.get("financial_metrics", [])
                        }
                    })

                    logger.info(f"[ENRICH] Extracted metadata for chunk {chunk.chunk_id}")

                except Exception as e:
                    logger.error(f"[ENRICH] Failed to extract metadata for chunk {chunk.chunk_id}: {type(e).__name__}: {e}")

            # Update progress
            _update_status(
                document_id,
                "enriching",
                f"Enriching metadata... ({min(i + batch_size, len(chunks))}/{len(chunks)} chunks)"
            )

        # Batch update in Qdrant
        if all_metadata_updates:
            updated = update_chunks_metadata_batch(document_id, all_metadata_updates)
            logger.info(f"[ENRICH] Updated {updated} chunks in Qdrant")

        # Update status: completed
        _update_status(
            document_id,
            "completed",
            None,
            indexed_chunks=len(chunks)
        )

        logger.info(f"[ENRICH] Completed metadata enrichment for {document_id}")

    except Exception as e:
        logger.error(f"[ENRICH] Failed metadata enrichment for {document_id}: {e}", exc_info=True)
        # Still mark as completed since indexing was successful
        _update_status(document_id, "completed", None, indexed_chunks=len(chunks))


def process_paddleocr_json_document_sync(document_id: str, ocr_json: list, source_file: str):
    """
    Background task: Process PaddleOCR-VL JSON document.
    """
    _run_sync_processing(document_id, ocr_json, source_file)


@router.post("")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """
    Upload and process a document.

    Supports:
    - .json: Direct indexing
    - .pdf: Async OCR -> Chunk -> Index
    """
    _ensure_data_dir()

    # Get file extension
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in [".json", ".pdf"]:
        raise HTTPException(
            status_code=400,
            detail="只支持 .json 和 .pdf 文件"
        )

    # Read file content
    content = await file.read()

    if file_ext == ".pdf":
        # === PDF Processing ===

        # Validate file size (100MB)
        if len(content) > 100 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="PDF 文件不能超过 100MB"
            )

        # Generate document ID
        document_id = str(uuid.uuid4())[:8]

        # Create task directory
        task_dir = _get_task_dir(document_id)

        # Save original PDF
        pdf_path = task_dir / "source.pdf"
        pdf_path.write_bytes(content)

        # Extract basic metadata from filename
        filename = file.filename
        company_name = filename.replace(".pdf", "").replace("_", " ").replace("-", " ")

        # Store initial metadata
        _documents[document_id] = {
            "document_id": document_id,
            "source_file": filename,
            "company_name": company_name,
        }

        # Create initial status
        _document_status[document_id] = DocumentStatus(
            document_id=document_id,
            status="pending",
            file_type="pdf",
            total_chunks=0,
            indexed_chunks=0,
            error=None,
            source_file=filename,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        _save_persistence()

        # Start background task
        background_tasks.add_task(process_pdf_document, document_id, pdf_path)

        return {
            "document_id": document_id,
            "status": "pending",
            "file_type": "pdf",
            "message": "PDF 上传成功，正在后台处理"
        }

    else:
        # === JSON Processing ===

        try:
            doc_data = json.loads(content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="无效的 JSON 文件")

        # 检测 JSON 格式
        if _is_paddleocr_format(doc_data):
            # === PaddleOCR-VL 格式：异步处理 ===
            logger.info(f"Upload: {file.filename} (PaddleOCR format)")

            # Generate document ID
            document_id = str(uuid.uuid4())[:8]

            # Extract company name from filename
            filename = file.filename
            company_name = filename.replace("_by_PaddleOCR-VL", "").replace(".json", "").replace("_", " ")

            # Store initial metadata
            _documents[document_id] = {
                "document_id": document_id,
                "source_file": filename,
                "company_name": company_name,
            }

            # Create initial status
            _document_status[document_id] = DocumentStatus(
                document_id=document_id,
                status="pending",
                file_type="json",
                total_chunks=0,
                indexed_chunks=0,
                error=None,
                source_file=filename,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            _save_persistence()

            # Start background task
            background_tasks.add_task(process_paddleocr_json_document_sync, document_id, doc_data, filename)

            return {
                "document_id": document_id,
                "status": "pending",
                "file_type": "json",
                "message": "PaddleOCR JSON 上传成功，正在后台处理"
            }

        else:
            # === DocumentSchema 格式：直接索引（兼容旧逻辑） ===
            logger.info(f"Detected DocumentSchema format JSON: {file.filename}")

            # Get document ID
            document_id = doc_data.get("document_id") or doc_data.get("document", {}).get("document_id")
            if not document_id:
                raise HTTPException(status_code=400, detail="JSON 中缺少 document_id")

            # Extract document metadata
            doc_meta = doc_data.get("document", doc_data)

            # Save file
            file_path = DATA_PATH / "uploads" / f"{document_id}.json"
            file_path.write_bytes(content)

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
                "page_count": doc_meta.get("page_count", len(doc_data.get("chunks", [])))
            }

            # Create initial status
            _document_status[document_id] = DocumentStatus(
                document_id=document_id,
                status="indexing",
                file_type="json",
                total_chunks=0,
                indexed_chunks=0,
                error=None,
                source_file=file.filename,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            _save_persistence()

            # Index document
            try:
                doc_schema = DocumentSchema(**doc_data)
                index_document(doc_schema)

                _document_status[document_id].status = "completed"
                _document_status[document_id].total_chunks = len(doc_schema.chunks)
                _document_status[document_id].indexed_chunks = len(doc_schema.chunks)
                _document_status[document_id].updated_at = datetime.now()
                _save_persistence()

            except Exception as e:
                logger.error(f"Failed to index document {document_id}: {e}")
                _document_status[document_id].status = "failed"
                _document_status[document_id].error = str(e)
                _document_status[document_id].updated_at = datetime.now()
                _save_persistence()

            return {
                "document_id": document_id,
                "status": "completed",
                "file_type": "json"
            }


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
    """Get document processing status."""
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
