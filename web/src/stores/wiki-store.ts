import { create } from 'zustand'

interface WikiPage {
  id: string
  title: string
  type: string
}

interface WikiState {
  pages: WikiPage[]
  loading: boolean
  error: string | null
  loadPages: () => Promise<void>
}

export const useWikiStore = create<WikiState>((set) => ({
  pages: [],
  loading: false,
  error: null,

  loadPages: async () => {
    set({ loading: true, error: null })
    try {
      const response = await fetch('/api/v1/projects')
      const data = await response.json()

      // For now, use mock data until we have a proper project ID
      // In production, we'd fetch from /api/v1/projects/{id}/wiki
      set({
        pages: [
          { id: 'overview', title: 'Overview', type: 'synthesis' },
          { id: 'example-entity', title: 'Example Entity', type: 'entity' },
          { id: 'example-concept', title: 'Example Concept', type: 'concept' },
        ],
        loading: false,
      })
    } catch (error) {
      set({ error: String(error), loading: false })
    }
  },
}))