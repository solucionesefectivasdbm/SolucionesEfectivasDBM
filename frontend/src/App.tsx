import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import ErrorBoundary from '@/components/ErrorBoundary'
import { LoadingPage } from '@/components/ui'
import Layout from '@/components/layout/Layout'
import LoginPage from '@/pages/Login/LoginPage'
import DashboardPage from '@/pages/Dashboard/DashboardPage'
import PagosPage from '@/pages/Pagos/PagosPage'
import CreditosPage from '@/pages/Creditos/CreditosPage'
import ClientesPage from '@/pages/Clientes/ClientesPage'
import UsuariosPage from '@/pages/Usuarios/UsuariosPage'
import ReceptoresPage from '@/pages/Receptores/ReceptoresPage'
import ReportesPage from '@/pages/Reportes/ReportesPage'
import CambiarPasswordPage from '@/pages/CambiarPassword/CambiarPasswordPage'
import GestoresPage from '@/pages/Gestores/GestoresPage'
import AuditoriaPage from '@/pages/Auditoria/AuditoriaPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

function RequireMustChange({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (user?.must_change_password) {
    return <Navigate to="/cambiar-password" replace />
  }
  return <>{children}</>
}

export default function App() {
  const initializing = useAuthStore((s) => s.initializing)
  const init = useAuthStore((s) => s.init)

  // Al montar la app, intentar restaurar sesión con la cookie de refresh
  useEffect(() => { init() }, [init])

  // Mientras intenta restaurar sesión, mostrar spinner (evita flash a /login)
  if (initializing) return <LoadingPage />

  return (
    <ErrorBoundary>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/cambiar-password" element={
          <RequireAuth><CambiarPasswordPage /></RequireAuth>
        } />
        <Route path="/" element={
          <RequireAuth>
            <RequireMustChange>
              <Layout />
            </RequireMustChange>
          </RequireAuth>
        }>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="pagos" element={<PagosPage variante="regular" />} />
          <Route path="pagos/semanales" element={<PagosPage variante="semanal" />} />
          <Route path="pagos/diarios" element={<PagosPage variante="diario" />} />
          <Route path="creditos" element={<CreditosPage />} />
          <Route path="clientes" element={<ClientesPage />} />
          <Route path="usuarios" element={<UsuariosPage />} />
          <Route path="receptores" element={<ReceptoresPage />} />
          <Route path="reportes" element={<ReportesPage />} />
          <Route path="gestores" element={<GestoresPage />} />
          <Route path="auditoria" element={<AuditoriaPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
    </ErrorBoundary>
  )
}
