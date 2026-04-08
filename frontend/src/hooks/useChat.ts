import { useState, useCallback, useRef } from 'react'
import type { ChatMessage, Citation } from '../types'
import { chatApi } from '../services/api'

import { generateId } from '../utils/helpers'

interface UseChatReturn {
  messages: ChatMessage[]
  isLoading: boolean
  sendMessage: (params: { document_id: string; query: string }) => void
  error: string | null
  reset: () => void
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const reset = useCallback(() => {
    setMessages([])
    setError(null)
    setIsLoading(false)
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
  }, [])

  const sendMessage = useCallback((params: { document_id: string; query: string }) => {
    const userMessage: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: params.query,
      timestamp: new Date(),
    }

    const assistantMessage: ChatMessage = {
      id: generateId(),
      role: 'assistant',
      content: '',
      citations: [],
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setIsLoading(true)
    setError(null)

    // Close any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const eventSource = chatApi.stream(params.document_id, params.query)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)

        if (data.type === 'token') {
          setMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantMessage.id
                ? { ...msg, content: msg.content + data.content }
                : msg
            )
          )
        } else if (data.type === 'citation') {
            const citation: Citation = {
              source_num: data.source_num,
              page_label: data.page_label || '',
              page_start: data.page_start,
              page_end: data.page_end,
              chunk_id: data.chunk_id,
              content: data.content,
              section_title: data.section_title,
            }
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === assistantMessage.id
                  ? { ...msg, citations: [...(msg.citations || []), citation] }
                  : msg
              )
            )
          } else if (data.type === 'done') {
            eventSource.close()
            setIsLoading(false)
            eventSourceRef.current = null
          } else if (data.type === 'error') {
            setError(data.message)
            eventSource.close()
            setIsLoading(false)
            eventSourceRef.current = null
          }
      } catch (e) {
        console.error('Failed to parse SSE event:', e)
      }
    }

    eventSource.onerror = () => {
      setError('Connection failed, please retry')
      eventSource.close()
      setIsLoading(false)
      eventSourceRef.current = null
    }
  }, [])

  return { messages, isLoading, sendMessage, error, reset }
}
