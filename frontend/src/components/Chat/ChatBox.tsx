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

  const handleCitationClick = (citation: Citation) => {
    setSelectedCitation(citation)
    setChunkContent(citation.content || 'No content available')
  }

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col">
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 ? (
            <div className="text-center text-gray-500 mt-20">
              <p className="text-lg mb-2">Ask a question</p>
              <p className="text-sm">e.g., What was the Q3 2024 revenue?</p>
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
              Thinking...
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <InputArea onSend={onSend} disabled={isLoading} />
      </div>

      {selectedCitation && (
        <div className="w-96 border-l border-gray-200 bg-gray-50 p-4 overflow-y-auto">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-medium">
              Source {selectedCitation.source_num}
              {selectedCitation.page_label && ` (${selectedCitation.page_label})`}
            </h3>
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
            {chunkContent || selectedCitation.content || 'Loading...'}
          </div>
        </div>
      )}
    </div>
  )
}
