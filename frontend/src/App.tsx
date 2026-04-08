import { useState, useRef, useCallback } from 'react'
import Sidebar from './components/Layout/Sidebar'
import Header from './components/Layout/Header'
import ChatBox from './components/Chat/ChatBox'
import { useChat } from './hooks/useChat'
import { documentApi } from './services/api'

function App() {
  const [currentDocId, setCurrentDocId] = useState<string | null>(null)
  const [currentDocTitle, setCurrentDocTitle] = useState<string | undefined>()
  const [sidebarWidth, setSidebarWidth] = useState(288) // 288px = w-72
  const { messages, isLoading, sendMessage, error, reset } = useChat()
  const isResizing = useRef(false)

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    isResizing.current = true

    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current) return
      const newWidth = Math.max(200, Math.min(600, e.clientX))
      setSidebarWidth(newWidth)
    }

    const handleMouseUp = () => {
      isResizing.current = false
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  const handleSelectDoc = (docId: string) => {
    setCurrentDocId(docId)
  }

  const handleSend = (query: string) => {
    if (currentDocId) {
      sendMessage({ document_id: currentDocId, query })
    }
  }

  return (
    <div className="flex h-screen bg-gray-100">
      <div style={{ width: sidebarWidth, minWidth: sidebarWidth }} className="flex-shrink-0">
        <Sidebar
          currentDocId={currentDocId}
          onSelectDoc={handleSelectDoc}
        />
      </div>

      {/* Resize handle */}
      <div
        onMouseDown={handleMouseDown}
        className="w-1 cursor-col-resize bg-gray-200 hover:bg-blue-400 active:bg-blue-500 transition-colors flex-shrink-0"
      />

      <div className="flex-1 flex flex-col min-w-0">
        <Header documentTitle={currentDocTitle} />

        {error && (
          <div className="bg-red-100 text-red-700 px-4 py-2 text-sm">
            {error}
          </div>
        )}

        <main className="flex-1 overflow-hidden">
          {currentDocId ? (
            <ChatBox
              documentId={currentDocId}
              messages={messages}
              isLoading={isLoading}
              onSend={handleSend}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              <div className="text-center">
                <p className="text-xl mb-2">Select or upload a financial report</p>
                <p className="text-sm">Supports JSON format structured financial data</p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default App
