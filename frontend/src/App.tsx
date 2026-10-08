import MeetingType from './pages/MeetingType'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import ConvertPage from './pages/ConvertPage'
import CustomerPage from './pages/CustomerPage'
import Home from './pages/Home'
import Login from './pages/Login'
import MeetingPage from './pages/MeetingPage'

function Routed() {
  const { staff, loading } = useAuth()
  if (loading) return <div className="splash">Loading…</div>
  if (!staff) return <Login />
  return (
    <Routes>
      <Route index element={<Home />} />
      <Route path="new-meeting" element={<MeetingType />} />
      <Route path="new-meeting/:kind" element={<MeetingType />} />
      <Route path="new" element={<MeetingPage key="new" />} />
      <Route path="new-lead" element={<ConvertPage />} />
      <Route path="customers/:id" element={<CustomerPage />} />
      <Route path="customers/:id/convert" element={<ConvertPage />} />
      <Route path="customers/:id/meeting" element={<MeetingPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <div className="app">
          <Routed />
        </div>
      </BrowserRouter>
    </AuthProvider>
  )
}
