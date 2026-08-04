import { useState } from 'react'
import Sidebar from './components/Sidebar'
import ChatPanel from './components/ChatPanel'
import PreviewPanel from './components/PreviewPanel'
import { useWikiStore } from './stores/wiki-store'

function App() {
  const [selectedPage, setSelectedPage] = useState<string | null>(null)
  const { pages, loadPages, loading } = useWikiStore()

  React.useEffect(() => {
    loadPages()
  }, [loadPages])

  return (
    <div className="flex h-screen bg-gray-100">
      {/* Sidebar - Wiki Tree */}
      <div className="w-64 bg-white border-r border-gray-200 overflow-auto">
        <Sidebar
          pages={pages}
          loading={loading}
          selectedPage={selectedPage}
          onSelectPage={setSelectedPage}
        />
      </div>

      {/* Main Content - Chat */}
      <div className="flex-1 flex flex-col">
        <ChatPanel selectedPage={selectedPage} />
      </div>

      {/* Preview Panel */}
      <div className="w-96 bg-white border-l border-gray-200 overflow-auto">
        <PreviewPanel pageId={selectedPage} />
      </div>
    </div>
  )
}

export default App