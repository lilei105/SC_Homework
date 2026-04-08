import type { Document, DocumentStatus } from '../../types'

// Status label mapping
const statusLabels: Record<string, { text: string; color: string }> = {
  pending: { text: 'Pending', color: 'text-gray-400' },
  parsing: { text: 'OCR Processing', color: 'text-yellow-400' },
  chunking: { text: 'Chunking', color: 'text-yellow-400' },
  indexing: { text: 'Indexing', color: 'text-yellow-400' },
  enriching: { text: 'Enriching Metadata', color: 'text-blue-400' },
  completed: { text: 'Completed', color: 'text-green-400' },
  failed: { text: 'Failed', color: 'text-red-400' },
}

interface DocListProps {
  documents: Document[]
  statuses: Record<string, DocumentStatus>
  currentDocId: string | null
  onSelect: (docId: string) => void
}

export default function DocList({ documents, statuses, currentDocId, onSelect }: DocListProps) {
  if (documents.length === 0) {
    return (
      <div className="px-4 py-8 text-gray-400 text-sm text-center">
        <p>No documents yet</p>
        <p className="text-xs mt-1">Click the button above to upload</p>
      </div>
    )
  }

  return (
    <ul className="space-y-1 px-2">
      {documents.map((doc) => {
        const status = statuses[doc.document_id]
        const isActive = currentDocId === doc.document_id
        const isReady = !status || status.status === 'completed'

        return (
          <li key={doc.document_id}>
            <button
              onClick={() => isReady && onSelect(doc.document_id)}
              disabled={!isReady}
              className={`w-full text-left px-3 py-2.5 rounded-lg transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : isReady
                  ? 'hover:bg-gray-700 text-gray-200'
                  : 'text-gray-500 cursor-not-allowed'
              }`}
            >
              <div className="font-medium text-sm truncate flex items-center gap-2">
                {doc.report_title || doc.company_name}
                {status?.file_type === 'pdf' && (
                  <span className="text-xs bg-orange-600 text-white px-1.5 py-0.5 rounded">PDF</span>
                )}
              </div>
              <div className="text-xs text-gray-400 truncate mt-0.5" title={doc.source_file}>
                {doc.source_file}
              </div>
              {status && status.status !== 'completed' && (
                <div className="mt-2">
                  <div className={`flex items-center gap-2 text-xs ${statusLabels[status.status]?.color || 'text-gray-400'}`}>
                    {status.status !== 'failed' && (
                      <div className="animate-spin w-3 h-3 border border-current border-t-transparent rounded-full" />
                    )}
                    {statusLabels[status.status]?.text || status.status}
                    {status.processing_stage && (
                      <span className="text-gray-500">({status.processing_stage})</span>
                    )}
                  </div>
                  {status.status === 'indexing' && status.total_chunks > 0 && (
                    <div className="text-xs text-gray-500 mt-1">
                      {status.indexed_chunks}/{status.total_chunks} chunks
                    </div>
                  )}
                  {status.status === 'failed' && status.error && (
                    <div className="text-xs text-red-400 mt-1 truncate" title={status.error}>
                      {status.error}
                    </div>
                  )}
                </div>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
