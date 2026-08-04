import { useState, useEffect } from 'react'

interface PreviewPanelProps {
  pageId: string | null
}

export default function PreviewPanel({ pageId }: PreviewPanelProps) {
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!pageId) {
      setContent('')
      return
    }

    setLoading(true)
    fetch(`/api/v1/wiki/${pageId}`)
      .then((res) => res.json())
      .then((data) => {
        setContent(data.body || '# No content')
        setLoading(false)
      })
      .catch(() => {
        setContent('# Error loading page')
        setLoading(false)
      })
  }, [pageId])

  if (!pageId) {
    return (
      <div className="p-4 text-center text-gray-400">
        Select a page to preview
      </div>
    )
  }

  if (loading) {
    return (
      <div className="p-4">
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-200 rounded w-3/4"></div>
          <div className="h-4 bg-gray-200 rounded w-1/2"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4">
      <div className="prose max-w-none">
        <pre className="whitespace-pre-wrap text-sm">{content}</pre>
      </div>
    </div>
  )
}