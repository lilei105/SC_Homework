import type { Document, DocumentStatus } from '../../types'

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
        <p>暂无文档</p>
        <p className="text-xs mt-1">点击上方按钮上传</p>
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
              <div className="font-medium text-sm truncate">
                {doc.company_name}
              </div>
              <div className="text-xs text-gray-400 truncate mt-0.5">
                {doc.fiscal_year} {doc.fiscal_period} · {doc.report_type}
              </div>
              {status && status.status !== 'completed' && (
                <div className="mt-2">
                  {status.status === 'indexing' ? (
                    <div className="flex items-center gap-2 text-xs text-yellow-400">
                      <div className="animate-spin w-3 h-3 border border-yellow-400 border-t-transparent rounded-full" />
                      索引中 {status.indexed_chunks}/{status.total_chunks}
                    </div>
                  ) : status.status === 'failed' ? (
                    <div className="text-xs text-red-400">索引失败</div>
                  ) : (
                    <div className="text-xs text-gray-400">等待中...</div>
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
