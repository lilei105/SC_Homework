import { useState, useEffect } from 'react'
import { documentApi } from '../../services/api'
import type { Document, DocumentStatus } from '../../types'
import UploadModal from '../Document/UploadModal'
import DocList from '../Document/DocList'

interface SidebarProps {
  currentDocId: string | null
  onSelectDoc: (docId: string) => void
}

export default function Sidebar({ currentDocId, onSelectDoc }: SidebarProps) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [statuses, setStatuses] = useState<Record<string, DocumentStatus>>({})
  const [showUpload, setShowUpload] = useState(false)
  const [loading, setLoading] = useState(false)

  const fetchDocuments = async () => {
    setLoading(true)
    try {
      const docs = await documentApi.list()
      setDocuments(docs)
    } catch (e) {
      console.error('Failed to fetch documents:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocuments()
  }, [])

  useEffect(() => {
    // Poll status for indexing documents
    const indexingDocs = Object.values(statuses).filter(
      (s) => s.status === 'indexing'
    )
    if (indexingDocs.length > 0) {
      const interval = setInterval(() => {
        indexingDocs.forEach(async (doc) => {
          try {
            const status = await documentApi.getStatus(doc.document_id)
            setStatuses((prev) => ({ ...prev, [doc.document_id]: status }))
          } catch (e) {
            console.error('Failed to poll status:', e)
          }
        })
      }, 2000)
      return () => clearInterval(interval)
    }
  }, [statuses])

  const handleUpload = async (file: File) => {
    try {
      const status = await documentApi.upload(file)
      await fetchDocuments()
      setStatuses((prev) => ({ ...prev, [status.document_id]: status }))
    } catch (e) {
      console.error('Upload failed:', e)
      alert('上传失败，请检查文件格式')
    }
    setShowUpload(false)
  }

  return (
    <aside className="w-72 bg-gray-800 text-white flex flex-col h-full">
      <div className="p-4 border-b border-gray-700">
        <h1 className="text-xl font-bold">Financial RAG</h1>
        <p className="text-xs text-gray-400 mt-1">财报智能问答系统</p>
      </div>

      <div className="p-4">
        <button
          onClick={() => setShowUpload(true)}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 px-4 rounded-lg font-medium transition-colors"
        >
          + 上传财报
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="px-4 py-2 text-xs text-gray-400 uppercase tracking-wide">
          已上传文档
        </div>
        {loading ? (
          <div className="px-4 py-2 text-gray-400 text-sm">加载中...</div>
        ) : (
          <DocList
            documents={documents}
            statuses={statuses}
            currentDocId={currentDocId}
            onSelect={onSelectDoc}
          />
        )}
      </div>

      {showUpload && (
        <UploadModal
          onClose={() => setShowUpload(false)}
          onUpload={handleUpload}
        />
      )}
    </aside>
  )
}
