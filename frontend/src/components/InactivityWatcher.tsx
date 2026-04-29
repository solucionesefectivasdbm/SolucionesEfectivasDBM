/**
 * InactivityWatcher — muestra aviso de inactividad y cierra sesión si no responde.
 *
 * - Tras 12 minutos sin actividad muestra el modal.
 * - El modal cuenta hacia atrás 3 minutos. Si llega a cero, ejecuta logout.
 * - "Continuar" reinicia el ciclo.
 *
 * Se monta solo cuando hay sesión activa (ver Layout).
 */
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import { useInactivityTimer } from '@/hooks/useInactivityTimer'
import Modal from '@/components/ui/Modal'
import { authApi } from '@/api'
import toast from 'react-hot-toast'

const INACTIVITY_MS = 12 * 60 * 1000 // 12 min
const GRACE_MS = 3 * 60 * 1000        // 3 min

export default function InactivityWatcher() {
  const isAuthenticated = useAuthStore(s => s.isAuthenticated)
  const logout = useAuthStore(s => s.logout)
  const navigate = useNavigate()

  const handleTimeout = async () => {
    try { await authApi.logout() } catch { /* ignorar */ }
    logout()
    toast('Sesión cerrada por inactividad', { icon: '⏱️' })
    navigate('/login', { replace: true })
  }

  const { warning, graceLeft, confirm } = useInactivityTimer({
    inactivityMs: INACTIVITY_MS,
    graceMs: GRACE_MS,
    onTimeout: handleTimeout,
    enabled: isAuthenticated,
  })

  const seconds = Math.ceil(graceLeft / 1000)
  const mm = Math.floor(seconds / 60)
  const ss = seconds % 60

  return (
    <Modal isOpen={warning} title="¿Sigue activo?" closable={false} size="sm">
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Hemos detectado <strong>12 minutos de inactividad</strong>. Por seguridad, su sesión se
          cerrará automáticamente si no confirma que sigue usando el sistema.
        </p>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-center">
          <p className="text-xs text-yellow-700 font-medium uppercase tracking-wider">Tiempo restante</p>
          <p className="text-2xl font-black text-yellow-800 font-mono mt-1">
            {String(mm).padStart(2, '0')}:{String(ss).padStart(2, '0')}
          </p>
        </div>
        <div className="flex justify-end gap-3">
          <button onClick={handleTimeout} className="btn-ghost">Cerrar sesión</button>
          <button onClick={confirm} className="btn-primary">Continuar sesión</button>
        </div>
      </div>
    </Modal>
  )
}
