import { useState, useRef, useEffect } from 'react'
import type { ChatMessage, ChunkData, Citation } from '../../types'
import Message from './Message'
import InputArea from './InputArea'
import { documentApi } from '../../services/api'

interface ChatBoxProps {
  documentId: string
  messages: ChatMessage[]
  isLoading: boolean
  onSend: (query: string) => void
}

export default function ChatBox({ documentId, messages, isLoading, onSend }: ChatBoxProps) {
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [chunkContent, setChunkContent] = useState<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleCitationClick = async (citation: Citation) => {
    setSelectedCitation(citation)
    if (citation.chunk_id) {
      try {
        const chunk = await documentApi.getChunk(documentId, citation.chunk_id)
        setChunkContent(chunk.content)
      } catch (e) {
        console.error('Failed to fetch chunk:', e)
        setChunkContent(citation.content || '无法加载原始内容')
      }
    }
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center text-gray-500 mt-20">
              <p className="text-lg mb-2">开始提问吧</p>
              <p className="text-sm">例如：2024年第三季度营收是多少？</p>
            </div>
          ) : (
            messages.map((msg) => (
              <Message
                key={msg.id}
                message={msg}
                onCitationClick={handleCitationClick}
              />
            ))
          )}
          {isLoading && messages.length > 0 && messages[messages.length - 1]?.role === 'assistant' && messages[messages.length - 1]?.content === '' && (
            <div className="flex items-center gap-2 text-gray-500">
              <div className="animate-spin w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full" />
              思考中...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <InputArea onSend={onSend} disabled={isLoading} />
      </div>

      {selectedCitation && (
        <div className="w-96 border-l border-gray-200 bg-gray-50 p-4 overflow-y-auto">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-medium">引用来源 (Page {selectedCitation.page})</h3>
            <button
              onClick={() => {
                setSelectedCitation(null)
                setChunkContent('')
              }}
              className="text-gray-500 hover:text-gray-700"
            >
              ✕
            </button>
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap">
            {chunkContent || selectedCitation.content || '加载中...'}
          </div>
        </div>
      )}
    </div>
  )
}
