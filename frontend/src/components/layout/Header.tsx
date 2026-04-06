import { useState, useEffect } from 'react'
import { Bell, LogOut, User, ChevronDown } from 'lucide-react'
import { useAuthStore } from '@/store/authStore'
import { pagosApi, authApi } from '@/api'
import { useNavigate } from 'react-router-dom'
import { formatCOP, formatFecha } from '@/utils/formatters'
import type { Pago, AlertasVencidos } from '@/types'
import toast from 'react-hot-toast'

export default function Header() {
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const [showAlerts, setShowAlerts] = useState(false)
  const [showUser, setShowUser] = useState(false)
  const [proximos, setProximos] = useState<Pago[]>([])
  const [vencidos, setVencidos] = useState<AlertasVencidos | null>(null)

  const totalAlertas = proximos.length + (vencidos?.total_pagos_vencidos ?? 0)

  useEffect(() => {
    cargarAlertas()
    const interval = setInterval(cargarAlertas, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const cargarAlertas = async () => {
    try {
      const [p, v] = await Promise.all([
        pagosApi.alertasProximosVencer(),
        pagosApi.alertasVencidos(),
      ])
      setProximos(p.data)
      setVencidos(v.data)
    } catch {}
  }

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {}
    logout()
    navigate('/login')
  }

  const ROLES: Record<string, string> = {
    admin: 'Administrador',
    registrador: 'Registrador',
    recaudador: 'Recaudador',
    gestor: 'Gestor',
  }

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shadow-sm">
      <div />

      <div className="flex items-center gap-3">
        {/* Campana de alertas */}
        <div className="relative">
          <button
            onClick={() => { setShowAlerts(!showAlerts); setShowUser(false) }}
            className="relative p-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <Bell size={20} className="text-primary-600" />
            {totalAlertas > 0 && (
              <span className="absolute -top-0.5 -right-0.5 w-5 h-5 bg-danger text-white text-xs rounded-full flex items-center justify-center font-bold">
                {totalAlertas > 9 ? '9+' : totalAlertas}
              </span>
            )}
          </button>

          {showAlerts && (
            <div className="absolute right-0 top-12 w-96 bg-white rounded-xl shadow-2xl border border-gray-100 z-50 max-h-[480px] overflow-hidden flex flex-col">
              <div className="px-4 py-3 bg-primary-600 text-white rounded-t-xl">
                <p className="font-semibold text-sm">Alertas de Cartera</p>
              </div>

              <div className="overflow-y-auto flex-1">
                {/* Vencidos */}
                {vencidos && vencidos.total_pagos_vencidos > 0 && (
                  <div className="p-3 bg-red-50 border-b border-red-100">
                    <p className="text-xs font-bold text-danger uppercase tracking-wide mb-1">
                      Atrasados — {vencidos.total_pagos_vencidos} pago(s)
                    </p>
                    <p className="text-sm font-semibold text-danger">
                      {formatCOP(vencidos.total_monto_mora)}
                    </p>
                  </div>
                )}

                {/* Próximos a vencer */}
                {proximos.length > 0 && (
                  <div>
                    <p className="px-3 pt-3 pb-1 text-xs font-bold text-yellow-700 uppercase tracking-wide">
                      Próximos a vencer ({proximos.length})
                    </p>
                    {proximos.map((p) => (
                      <div key={p.id} className="px-3 py-2 border-b border-gray-50 hover:bg-yellow-50">
                        <p className="text-xs font-medium text-gray-700">Cuota #{p.numero_cuota}</p>
                        <p className="text-xs text-gray-500">Vence: {formatFecha(p.fecha_maxima)}</p>
                        <p className="text-xs font-semibold text-primary-600">{formatCOP(p.monto_a_pagar)}</p>
                      </div>
                    ))}
                  </div>
                )}

                {totalAlertas === 0 && (
                  <div className="p-6 text-center text-gray-400 text-sm">
                    Sin alertas pendientes ✓
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Usuario */}
        <div className="relative">
          <button
            onClick={() => { setShowUser(!showUser); setShowAlerts(false) }}
            className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <div className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center">
              <User size={16} className="text-white" />
            </div>
            <div className="text-left hidden md:block">
              <p className="text-sm font-semibold text-gray-800 leading-tight">{user?.username}</p>
              <p className="text-xs text-gray-500 leading-tight">{ROLES[user?.tipo_usuario ?? '']}</p>
            </div>
            <ChevronDown size={16} className="text-gray-400" />
          </button>

          {showUser && (
            <div className="absolute right-0 top-12 w-48 bg-white rounded-xl shadow-2xl border border-gray-100 z-50 overflow-hidden">
              <button
                onClick={handleLogout}
                className="w-full flex items-center gap-2 px-4 py-3 text-sm text-danger hover:bg-red-50 transition-colors"
              >
                <LogOut size={16} />
                Cerrar sesión
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Overlay para cerrar dropdowns */}
      {(showAlerts || showUser) && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => { setShowAlerts(false); setShowUser(false) }}
        />
      )}
    </header>
  )
}
