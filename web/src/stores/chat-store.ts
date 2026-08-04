import { create } from 'zustand'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
}

interface ChatState {
  messages: Message[]
  loading: boolean
  sendMessage: (content: string) => Promise<void>
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  loading: false,

  sendMessage: async (content: string) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
    }

    set((state) => ({
      messages: [...state.messages, userMessage],
      loading: true,
    }))

    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: content }),
      })

      const data = await response.json()

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.response || data.answer || 'Sorry, I could not process that.',
      }

      set((state) => ({
        messages: [...state.messages, assistantMessage],
        loading: false,
      }))
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${error}`,
      }

      set((state) => ({
        messages: [...state.messages, errorMessage],
        loading: false,
      }))
    }
  },
}))