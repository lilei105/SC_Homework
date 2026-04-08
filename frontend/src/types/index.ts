export interface PeriodInfo {
  fiscal_year: number
  fiscal_period: string
  date_label: string
  start_date?: string
  end_date?: string
}

export interface FinancialMetric {
  name: string
  value: string
  normalized_value: number
  unit: string
  period_label: string
}

export interface Entities {
  company: string[]
  products: string[]
  regions: string[]
  people: string[]
}

export interface TableData {
  table_title?: string
  unit?: string
  headers: string[]
  rows: string[][]
}

export interface ChunkData {
  chunk_id: string
  chunk_index: number
  section_id: string
  section_title: string
  section_summary?: string
  page_start: number
  page_end: number
  chunk_type: 'text' | 'table' | 'figure' | 'mixed'
  content: string
  content_brief?: string
  keywords?: string[]
  period?: PeriodInfo
  entities?: Entities
  table_data?: TableData
  financial_metrics?: FinancialMetric[]
}

export interface Document {
  document_id: string
  source_file: string
  company_name: string
  ticker?: string
  report_type: string
  report_title: string
  language: string
  currency: string
  fiscal_year: number
  fiscal_period: string
  report_date?: string
  page_count?: number
}

export interface DocumentStatus {
  document_id: string
  status: 'pending' | 'parsing' | 'chunking' | 'indexing' | 'completed' | 'failed'
  file_type?: 'pdf' | 'json'
  total_chunks: number
  indexed_chunks: number
  error?: string
  processing_stage?: string
  source_file?: string
  created_at?: string
  updated_at?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  timestamp: Date
}

export interface Citation {
  source_num: number
  page_label: string
  page_start?: number
  page_end?: number
  chunk_id: string
  content: string
  section_title?: string
}
