import ReactMarkdown from 'react-markdown'
import type { ChatMessage, Citation } from '../../types'

interface MessageProps {
  message: ChatMessage
  onCitationClick: (citation: Citation) => void
}

export default function Message({ message, onCitationClick }: MessageProps) {
  const isUser = message.role === 'user'

  const renderContent = (content: string) => {
    // Match [Source N] pattern for citations (case-insensitive)
    const citationRegex = /\[Source\s+(\d+)\]/gi
    const parts: React.ReactNode[] = []
    let lastIndex = 0
    let match
    let key = 0

    while ((match = citationRegex.exec(content)) !== null) {
      // Add text before the match
      if (match.index > lastIndex) {
        parts.push(
          <span key={key++}>{content.slice(lastIndex, match.index)}</span>
        )
      }

      const sourceNum = parseInt(match[1])
      const citation = message.citations?.find((c) => c.source_num === sourceNum)

      if (citation) {
        parts.push(
          <button
            key={key++}
            onClick={() => onCitationClick(citation)}
            className="inline-flex items-center px-1.5 py-0.5 bg-blue-100 text-blue-700 text-xs rounded hover:bg-blue-200 cursor-pointer"
            title={citation.section_title || ''}
          >
            {citation.page_label || `Source ${sourceNum}`}
          </button>
        )
      } else {
        parts.push(
          <span key={key++} className="text-xs text-gray-500 bg-gray-100 px-1 py-0.5 rounded">
            [Source {sourceNum}]
          </span>
        )
      }

      lastIndex = match.index + match[0].length
    }

    // Add remaining text
    if (lastIndex < content.length) {
      parts.push(<span key={key++}>{content.slice(lastIndex)}</span>)
    }

    return parts.length > 0 ? parts : content
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-2xl rounded-lg px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white'
            : 'bg-white border border-gray-200 text-gray-800'
        }`}
      >
        <div className={`${isUser ? '' : 'prose prose-sm max-w-none'}`}>
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="whitespace-pre-wrap">{renderContent(message.content)}</div>
          )}
        </div>
        <div className={`text-xs mt-2 ${isUser ? 'text-blue-200' : 'text-gray-400'}`}>
          {message.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </div>
      </div>
    </div>
  )
}
