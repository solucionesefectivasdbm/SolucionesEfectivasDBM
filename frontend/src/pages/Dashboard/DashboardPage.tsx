import { useEffect, useState } from 'react'
import { pagosApi, clientesApi, creditosApi } from '@/api'
import { formatCOP, formatFecha } from '@/utils/formatters'
import { StatCard, LoadingPage, MoraBadge } from '@/components/ui'
import { useAuthStore } from '@/store/authStore'
import type { Pago, AlertasVencidos } from '@/types'
import { AlertTriangle, Clock } from 'lucide-react'

export default function DashboardPage() {
  const { user } = useAuthStore()
  const [loading, setLoading] = useState(true)
  const [proximos, setProximos] = useState<Pago[]>([])
  const [vencidos, setVencidos] = useState<AlertasVencidos | null>(null)
  const [totalClientes, setTotalClientes] = useState(0)
  const [totalCreditos, setTotalCreditos] = useState(0)
  const [saldoCartera, setSaldoCartera] = useState(0)

  useEffect(() => {
    const cargar = async () => {
      try {
        const [p, v, cl, cr, cartera] = await Promise.all([
          pagosApi.alertasProximosVencer(),
          pagosApi.alertasVencidos(),
          clientesApi.listar({ page: 1 }),
          creditosApi.listar({ page: 1, solo_activos: true }),
          creditosApi.resumenCartera(),
        ])
        setProximos(p.data)
        setVencidos(v.data)
        setTotalClientes(cl.data.total)
        setTotalCreditos(cr.data.total)
        setSaldoCartera(cartera.data.saldo_capital)
      } catch {}
      finally { setLoading(false) }
    }
    cargar()
  }, [])

  if (loading) return <LoadingPage />

  const ROLES: Record<string, string> = {
    admin: 'Administrador', registrador: 'Registrador',
    recaudador: 'Recaudador', gestor: 'Gestor',
  }

  return (
    <div className="space-y-6">
      {/* Saludo */}
      <div>
        <h1 className="text-2xl font-black text-primary-600">
          Bienvenido, {user?.username}
        </h1>
        <p className="text-gray-400 text-sm">{ROLES[user?.tipo_usuario ?? '']} · Panel de Control</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard
          label="Clientes"
          value={totalClientes}
          color="blue"
        />
        <StatCard
          label="Créditos Activos"
          value={totalCreditos}
          color="yellow"
        />
        <StatCard
          label="Saldo Cartera"
          value={formatCOP(saldoCartera)}
          sub="capital activo"
          color="blue"
        />
        <StatCard
          label="Pagos Próx. a Vencer"
          value={proximos.length}
          sub="en los próximos 3 días"
          color={proximos.length > 0 ? 'yellow' : 'green'}
        />
        <StatCard
          label="Pagos Atrasados"
          value={vencidos?.total_pagos_vencidos ?? 0}
          sub={vencidos ? formatCOP(vencidos.total_monto_mora) : '$ 0'}
          color={vencidos && vencidos.total_pagos_vencidos > 0 ? 'red' : 'green'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Próximos a vencer */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Clock size={18} className="text-accent-dark" />
            <h2 className="text-base font-bold text-gray-800">Próximos a vencer</h2>
          </div>
          {proximos.length === 0 ? (
            <p className="text-center text-gray-400 text-sm py-8">Sin pagos próximos a vencer ✓</p>
          ) : (
            <div className="space-y-2">
              {proximos.slice(0, 8).map((p) => (
                <div key={p.id} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
                  <div>
                    <p className="text-sm font-medium text-gray-700">Cuota #{p.numero_cuota}</p>
                    <p className="text-xs text-gray-400">Vence: {formatFecha(p.fecha_maxima)}</p>
                  </div>
                  <p className="text-sm font-bold text-primary-600">{formatCOP(p.monto_a_pagar)}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Atrasados */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={18} className="text-danger" />
            <h2 className="text-base font-bold text-gray-800">Pagos atrasados</h2>
          </div>
          {!vencidos || vencidos.total_pagos_vencidos === 0 ? (
            <p className="text-center text-gray-400 text-sm py-8">Sin pagos vencidos ✓</p>
          ) : (
            <>
              <div className="bg-red-50 rounded-lg p-3 mb-3 flex justify-between items-center">
                <span className="text-sm font-medium text-danger">Total atrasado</span>
                <span className="font-black text-danger">{formatCOP(vencidos.total_monto_mora)}</span>
              </div>
              <div className="space-y-2">
                {vencidos.pagos.slice(0, 6).map((p) => (
                  <div key={p.id} className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0">
                    <div>
                      <p className="text-sm font-medium text-gray-700">Cuota #{p.numero_cuota}</p>
                      <p className="text-xs text-gray-400">Venció: {formatFecha(p.fecha_maxima)}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-bold text-danger">{formatCOP(p.monto_a_pagar)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
