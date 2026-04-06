from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime


class PeriodInfo(BaseModel):
    fiscal_year: int
    fiscal_period: str
    date_label: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class FinancialMetric(BaseModel):
    name: str
    value: str
    normalized_value: float
    unit: str
    period_label: str


class Entities(BaseModel):
    company: List[str] = []
    products: List[str] = []
    regions: List[str] = []
    people: List[str] = []


class TableData(BaseModel):
    table_title: Optional[str] = None
    unit: Optional[str] = None
    headers: List[str] = []
    rows: List[List[str]] = []


class FigureData(BaseModel):
    figure_title: Optional[str] = None
    caption: Optional[str] = None
    description: Optional[str] = None


class SourceTrace(BaseModel):
    source_block_ids: List[str] = []
    raw_text_excerpt: Optional[str] = None
    ocr_confidence: Optional[float] = None


class Relations(BaseModel):
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None


class Flags(BaseModel):
    is_section_lead: bool = False
    is_table_title: bool = False
    is_table_continuation: bool = False
    is_figure_caption: bool = False
    is_key_financial_chunk: bool = False


class ChunkData(BaseModel):
    chunk_id: str
    chunk_index: int
    section_id: str
    section_title: str
    section_summary: Optional[str] = None
    page_start: int
    page_end: int
    chunk_type: Literal["text", "table", "figure", "mixed"]
    content: str
    content_brief: Optional[str] = None
    keywords: List[str] = []
    period: Optional[PeriodInfo] = None
    entities: Optional[Entities] = None
    table_data: Optional[TableData] = None
    figure_data: Optional[FigureData] = None
    financial_metrics: List[FinancialMetric] = []
    source_trace: Optional[SourceTrace] = None
    relations: Optional[Relations] = None
    bundle_id: Optional[str] = None
    flags: Optional[Flags] = None


class ParserInfo(BaseModel):
    provider: Optional[str] = None
    version: Optional[str] = None
    notes: Optional[str] = None


class DocumentMetadata(BaseModel):
    document_id: str
    source_file: str
    company_name: str
    ticker: Optional[str] = None
    report_type: str
    report_title: str
    language: str = "en"
    currency: str = "USD"
    fiscal_year: int
    fiscal_period: str
    report_date: Optional[str] = None
    page_count: Optional[int] = None
    parser: Optional[ParserInfo] = None


class Section(BaseModel):
    section_id: str
    title: str
    normalized_title: Optional[str] = None
    summary: Optional[str] = None
    page_start: int
    page_end: int


class DocumentSchema(BaseModel):
    schema_version: str = "1.0"
    document: DocumentMetadata
    sections: List[Section] = []
    chunks: List[ChunkData] = []


class DocumentStatus(BaseModel):
    document_id: str
    status: Literal["pending", "indexing", "completed", "failed"]
    total_chunks: int = 0
    indexed_chunks: int = 0
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ChatRequest(BaseModel):
    document_id: str
    query: str


class Citation(BaseModel):
    page: int
    chunk_id: str
    content: str
