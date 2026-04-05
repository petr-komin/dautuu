import { Outlet, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { Sidebar } from './Sidebar'
import { useAuthStore } from '../../store/authStore'

export function AppLayout() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0)

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  const activeConvId = searchParams.get('conv')

  function handleConversationSelect(id: string) {
    navigate(`/chat?conv=${id}`)
  }

  function handleNewConversation(projectId?: string | null) {
    if (projectId) {
      navigate(`/chat?project=${projectId}`)
    } else {
      navigate('/chat')
    }
  }

  function handleSidebarRefresh() {
    setSidebarRefreshKey((k) => k + 1)
  }

  return (
    <div className="flex h-full overflow-hidden">
      <Sidebar
        activeConvId={activeConvId}
        onConversationSelect={handleConversationSelect}
        onNewConversation={handleNewConversation}
        refreshKey={sidebarRefreshKey}
      />
      <main className="flex-1 overflow-auto">
        <Outlet context={{ onConversationCreated: handleSidebarRefresh }} />
      </main>
    </div>
  )
}
