import { useState, useRef } from 'react'

interface UploadModalProps {
  onClose: () => void
  onUpload: (file: File) => void
}

export default function UploadModal({ onClose, onUpload }: UploadModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    validateAndSetFile(selectedFile)
  }

  const validateAndSetFile = (selectedFile: File | undefined) => {
    if (!selectedFile) return

    const ext = selectedFile.name.split('.').pop()?.toLowerCase()

    if (ext === 'pdf') {
      // PDF 验证：大小 (100MB)
      if (selectedFile.size > 100 * 1024 * 1024) {
        setError('PDF 文件不能超过 100MB')
        return
      }
      setFile(selectedFile)
      setError(null)
    } else if (ext === 'json') {
      setFile(selectedFile)
      setError(null)
    } else {
      setError('请上传 PDF 或 JSON 格式文件')
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const droppedFile = e.dataTransfer.files[0]
    validateAndSetFile(droppedFile)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(true)
  }

  const handleDragLeave = () => {
    setDragOver(false)
  }

  const handleUpload = () => {
    if (file) {
      onUpload(file)
    }
  }

  const isPdf = file?.name.endsWith('.pdf')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-[480px] shadow-2xl">
        <h3 className="text-lg font-semibold mb-4">上传财报文档</h3>

        <div
          onClick={() => inputRef.current?.click()}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragOver
              ? 'border-blue-500 bg-blue-50'
              : file
              ? 'border-green-500 bg-green-50'
              : 'border-gray-300 hover:border-blue-400'
          }`}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.json"
            onChange={handleFileChange}
            className="hidden"
          />
          {file ? (
            <div>
              <div className="text-green-600 text-4xl mb-2">✓</div>
              <p className="text-gray-700 font-medium">{file.name}</p>
              <p className="text-gray-500 text-sm mt-1">
                {(file.size / 1024).toFixed(1)} KB
                {isPdf && ' · PDF 将自动 OCR 识别'}
              </p>
            </div>
          ) : (
            <div>
              <div className="text-gray-400 text-4xl mb-2">📄</div>
              <p className="text-gray-600">点击或拖拽文件到此处</p>
              <p className="text-gray-400 text-sm mt-1">支持 PDF 和 JSON 格式</p>
              <p className="text-gray-400 text-xs mt-1">PDF 最大 500 页，100MB</p>
            </div>
          )}
        </div>

        {error && (
          <p className="text-red-500 text-sm mt-2">{error}</p>
        )}

        <div className="flex justify-end gap-3 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleUpload}
            disabled={!file}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isPdf ? '上传并处理' : '上传并索引'}
          </button>
        </div>
      </div>
    </div>
  )
}
