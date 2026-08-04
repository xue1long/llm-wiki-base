import { WikiPage } from '../stores/wiki-store'

interface SidebarProps {
  pages: WikiPage[]
  loading: boolean
  selectedPage: string | null
  onSelectPage: (id: string) => void
}

export default function Sidebar({ pages, loading, selectedPage, onSelectPage }: SidebarProps) {
  if (loading) {
    return (
      <div className="p-4">
        <div className="animate-pulse space-y-2">
          <div className="h-4 bg-gray-200 rounded w-3/4"></div>
          <div className="h-4 bg-gray-200 rounded w-1/2"></div>
          <div className="h-4 bg-gray-200 rounded w-2/3"></div>
        </div>
      </div>
    )
  }

  const groupedPages = pages.reduce((acc, page) => {
    const type = page.type || 'other'
    if (!acc[type]) acc[type] = []
    acc[type].push(page)
    return acc
  }, {} as Record<string, WikiPage[]>)

  return (
    <div className="p-4">
      <h1 className="text-xl font-bold mb-4">ruflo-kb</h1>

      {Object.entries(groupedPages).map(([type, typePages]) => (
        <div key={type} className="mb-4">
          <h2 className="text-xs font-semibold text-gray-500 uppercase mb-2">{type}</h2>
          <ul className="space-y-1">
            {typePages.map((page) => (
              <li key={page.id}>
                <button
                  onClick={() => onSelectPage(page.id)}
                  className={`w-full text-left px-2 py-1 rounded text-sm ${
                    selectedPage === page.id
                      ? 'bg-blue-100 text-blue-800'
                      : 'hover:bg-gray-100'
                  }`}
                >
                  {page.title}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}