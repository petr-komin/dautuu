import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'

import { AppLayout } from './components/layout/AppLayout'
import { SettingsLayout } from './components/layout/SettingsLayout'
import { LoginPage } from './pages/LoginPage'
import { ChatPage } from './pages/ChatPage'
import { UsagePage } from './pages/UsagePage'
import { ModelPage } from './pages/ModelPage'
import { McpPage } from './pages/McpPage'
import { McpClientsPage } from './pages/McpClientsPage'
import { ConnectionPage } from './pages/ConnectionPage'

export default function App() {
  return (
    <BrowserRouter>
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: 'var(--surface)',
            color: 'var(--text)',
            border: '1px solid var(--border)',
            fontSize: '13px',
          },
        }}
      />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AppLayout />}>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/settings" element={<SettingsLayout />}>
            <Route index element={<Navigate to="model" replace />} />
            <Route path="model" element={<ModelPage />} />
            <Route path="mcp" element={<McpPage />} />
            <Route path="mcp-clients" element={<McpClientsPage />} />
            <Route path="connection" element={<ConnectionPage />} />
          </Route>
          <Route path="/" element={<Navigate to="/chat" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
