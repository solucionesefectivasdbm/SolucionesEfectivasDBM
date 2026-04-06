import { useState } from 'react'
import { reportesApi } from '@/api'
import { formatCOP, MESES, MOMENTOS, aniosDisponibles } from '@/utils/formatters'
import { LoadingPage } from '@/components/ui'
import toast from 'react-hot-toast'
import { BarChart3 } from 'lucide-react'

export default function ReportesPage() {
  const hoy = new Date()
  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [momento, setMomento] = useState('')
  const [reporte, setReporte] = useState<any | null>(null)
  const [loading, setLoading] = useState(false)

  const generarReporte = async () => {
    if (!momento) { toast.error('Selecciona el momento'); return }
    setLoading(true)
    try {
      const res = await reportesApi.generar({ anio, mes, momento })
      setReporte(res.data)
    } catch { toast.error('Error al generar reporte') }
    finally { setLoading(false) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BarChart3 size={28} className="text-primary-600" />
        <h1 className="text-2xl font-black text-primary-600">Reportes Financieros</h1>
      </div>

      {/* Filtros */}
      <div className="card">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
          <div>
            <label className="label">Año *</label>
            <select className="input" value={anio} onChange={e => setAnio(+e.target.value)}>
              {aniosDisponibles().map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Mes *</label>
            <select className="input" value={mes} onChange={e => setMes(+e.target.value)}>
              {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Momento *</label>
            <select className="input" value={momento} onChange={e => setMomento(e.target.value)}>
              <option value="">-- Seleccionar --</option>
              {MOMENTOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <button onClick={generarReporte} disabled={loading} className="btn-primary py-2.5">
            {loading ? 'Generando...' : 'Generar Reporte'}
          </button>
        </div>
      </div>

      {loading && <LoadingPage />}

      {reporte && !loading && (
        <div className="space-y-6">

          {/* Totales generales */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Recaudado */}
            <div className="card bg-primary-600 text-white border-0 space-y-2">
              <p className="text-xs font-bold uppercase tracking-wider opacity-70">Recaudado</p>
              <p className="text-2xl font-black">{formatCOP(reporte.total_recaudado)}</p>
              <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-primary-400">
                <div className="flex justify-between">
                  <span>Capital</span>
                  <span>{formatCOP(reporte.total_capital_recaudado)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Intereses</span>
                  <span>{formatCOP(reporte.total_intereses_recaudados)}</span>
                </div>
              </div>
            </div>

            {/* Pendiente */}
            <div className="card bg-yellow-500 text-white border-0 space-y-2">
              <p className="text-xs font-bold uppercase tracking-wider opacity-70">Pendiente</p>
              <p className="text-2xl font-black">{formatCOP(reporte.total_pendiente)}</p>
              <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-yellow-400">
                <div className="flex justify-between">
                  <span>Capital</span>
                  <span>{formatCOP(reporte.total_capital_pendiente)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Intereses</span>
                  <span>{formatCOP(reporte.total_intereses_pendientes)}</span>
                </div>
              </div>
            </div>

            {/* Total esperado */}
            <div className="card bg-primary-800 text-white border-0 space-y-2">
              <p className="text-xs font-bold uppercase tracking-wider opacity-70">Total Esperado</p>
              <p className="text-2xl font-black">{formatCOP(reporte.total_esperado)}</p>
              <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-primary-600">
                <div className="flex justify-between">
                  <span>Recaudado</span>
                  <span>{formatCOP(reporte.total_recaudado)}</span>
                </div>
                <div className="flex justify-between">
                  <span>Pendiente</span>
                  <span>{formatCOP(reporte.total_pendiente)}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Por Gestor */}
          <div className="card">
            <h2 className="text-base font-bold text-primary-600 mb-4">Desglose por Gestor</h2>
            {reporte.por_gestor.length === 0
              ? <p className="text-gray-400 text-sm text-center py-4">Sin datos</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr>
                        <th className="table-header">Gestor</th>
                        <th className="table-header">Recaudado</th>
                        <th className="table-header">Capital Rec.</th>
                        <th className="table-header">Intereses Rec.</th>
                        <th className="table-header">Pendiente</th>
                        <th className="table-header">Capital Pend.</th>
                        <th className="table-header">Intereses Pend.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reporte.por_gestor.map((g: any, i: number) => (
                        <tr key={g.gestor_id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                          <td className="table-cell font-medium">{g.gestor_nombre}</td>
                          <td className="table-cell font-bold text-primary-600">{formatCOP(g.total_recaudado)}</td>
                          <td className="table-cell">{formatCOP(g.total_capital_recaudado)}</td>
                          <td className="table-cell">{formatCOP(g.total_intereses_recaudados)}</td>
                          <td className="table-cell font-bold text-yellow-600">{formatCOP(g.total_pendiente)}</td>
                          <td className="table-cell">{formatCOP(g.total_capital_pendiente)}</td>
                          <td className="table-cell">{formatCOP(g.total_intereses_pendientes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </div>

          {/* Por Receptor */}
          <div className="card">
            <h2 className="text-base font-bold text-primary-600 mb-4">Desglose por Receptor</h2>
            {reporte.por_receptor.length === 0
              ? <p className="text-gray-400 text-sm text-center py-4">Sin datos</p>
              : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr>
                        <th className="table-header">Receptor</th>
                        <th className="table-header">Recaudado</th>
                        <th className="table-header">Capital Rec.</th>
                        <th className="table-header">Intereses Rec.</th>
                        <th className="table-header">Pendiente</th>
                        <th className="table-header">Capital Pend.</th>
                        <th className="table-header">Intereses Pend.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reporte.por_receptor.map((r: any, i: number) => (
                        <tr key={r.receptor_id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                          <td className="table-cell font-medium">{r.receptor_nombre}</td>
                          <td className="table-cell font-bold text-primary-600">{formatCOP(r.total_recaudado)}</td>
                          <td className="table-cell">{formatCOP(r.total_capital_recaudado)}</td>
                          <td className="table-cell">{formatCOP(r.total_intereses_recaudados)}</td>
                          <td className="table-cell font-bold text-yellow-600">{formatCOP(r.total_pendiente)}</td>
                          <td className="table-cell">{formatCOP(r.total_capital_pendiente)}</td>
                          <td className="table-cell">{formatCOP(r.total_intereses_pendientes)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </div>

        </div>
      )}
    </div>
  )
}