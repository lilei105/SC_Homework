import axios from 'axios'
import type { DocumentStatus, Document, ChunkData } from '../types'

const api = axios.create({
  baseURL: '/api/v1',
})

export const documentApi = {
  upload: async (file: File): Promise<DocumentStatus> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await api.post<DocumentStatus>('/documents', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return response.data
  },

  list: async (): Promise<Document[]> => {
    const response = await api.get<Document[]>('/documents')
    return response.data
  },

  get: async (documentId: string): Promise<Document> => {
    const response = await api.get<Document>(`/documents/${documentId}`)
    return response.data
  },

  getStatus: async (documentId: string): Promise<DocumentStatus> => {
    const response = await api.get<DocumentStatus>(`/documents/${documentId}/status`)
    return response.data
  },

  getChunk: async (documentId: string, chunkId: string): Promise<ChunkData> => {
    const response = await api.get<ChunkData>(`/documents/${documentId}/chunks/${chunkId}`)
    return response.data
  },
}

export const chatApi = {
  stream: (documentId: string, query: string): EventSource => {
    const params = new URLSearchParams({
      document_id: documentId,
      query: query,
    })
    return new EventSource(`/api/v1/chat?${params.toString()}`)
  },
}
