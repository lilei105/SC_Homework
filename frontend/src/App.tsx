import { useState, useEffect } from 'react'
import Sidebar from './components/Layout/Sidebar'
import Header from './components/Layout/Header'
import ChatBox from './components/Chat/ChatBox'
import { useChat } from './hooks/useChat'
import { documentApi } from './services/api'

function App() {
  const [currentDocId, setCurrentDocId] = useState<string | null>(null)
  const [currentDocTitle, setCurrentDocTitle] = useState<string | undefined>()
  const { messages, isLoading, sendMessage, error, reset } = useChat()

  useEffect(() => {
    if (currentDocId) {
      reset()
      documentApi.get(currentDocId)
        .then((doc) => setCurrentDocTitle(doc.report_title))
        .catch(console.error)
    } else {
      setCurrentDocTitle(undefined)
    }
  }, [currentDocId, reset])

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
      <Sidebar
        currentDocId={currentDocId}
        onSelectDoc={handleSelectDoc}
      />

      <div className="flex-1 flex flex-col">
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
                <p className="text-xl mb-2">请选择或上传财报文档</p>
                <p className="text-sm">支持 JSON 格式的结构化财报数据</p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default App
