import { useState, useEffect, useCallback } from 'react'
import { auditoriaApi } from '@/api'
import { LoadingPage, EmptyState, Paginacion } from '@/components/ui'
import { Search } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface AuditEntry {
  id: string
  entidad: string
  entidad_id: string
  accion: string
  campo_modificado: string | null
  valor_anterior: string | null
  valor_nuevo: string | null
  usuario_id: string
  usuario_username: string | null
  fecha_accion: string
  ip_origen: string
}

const ENTIDADES = ['', 'clientes', 'creditos', 'pagos', 'usuarios', 'gestores', 'receptores']
const ACCION_COLORS: Record<string, string> = {
  CREATE: 'badge-success',
  UPDATE: 'badge-info',
  DELETE: 'badge-danger',
}

export default function AuditoriaPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)

  const [entidad, setEntidad] = useState('')
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')
  const [entidadId, setEntidadId] = useState('')

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { page }
      if (entidad) params.entidad = entidad
      if (fechaDesde) params.fecha_desde = fechaDesde
      if (fechaHasta) params.fecha_hasta = fechaHasta
      if (entidadId) params.entidad_id = entidadId

      const res = await auditoriaApi.listar(params)
      setEntries(res.data.items || res.data)
      setTotal(res.data.total || (res.data.length ?? 0))
      setPages(res.data.pages || 1)
    } catch {
      toast.error('Error al cargar auditoría')
    } finally {
      setLoading(false)
    }
  }, [page, entidad, fechaDesde, fechaHasta, entidadId])

  useEffect(() => { cargar() }, [cargar])

  const formatDate = (d: string) => {
    const date = new Date(d)
    return date.toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' })
  }

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-black text-primary-600">Historial de Auditoría</h1>

      {/* Filtros */}
      <div className="card">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="label">Entidad</label>
            <select className="input" value={entidad} onChange={e => { setEntidad(e.target.value); setPage(1) }}>
              <option value="">Todas</option>
              {ENTIDADES.filter(Boolean).map(e => (
                <option key={e} value={e}>{e.charAt(0).toUpperCase() + e.slice(1)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Desde</label>
            <input type="date" className="input" value={fechaDesde}
              onChange={e => { setFechaDesde(e.target.value); setPage(1) }} />
          </div>
          <div>
            <label className="label">Hasta</label>
            <input type="date" className="input" value={fechaHasta}
              onChange={e => { setFechaHasta(e.target.value); setPage(1) }} />
          </div>
          <div>
            <label className="label">ID de entidad</label>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input className="input pl-9" placeholder="UUID..."
                value={entidadId} onChange={e => { setEntidadId(e.target.value); setPage(1) }} />
            </div>
          </div>
        </div>
      </div>

      {/* Tabla */}
      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : entries.length === 0 ? (
          <EmptyState message="No hay registros de auditoría" />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="table-header">Fecha</th>
                    <th className="table-header">Usuario</th>
                    <th className="table-header">Entidad</th>
                    <th className="table-header">Acción</th>
                    <th className="table-header">Campo</th>
                    <th className="table-header">Valor anterior</th>
                    <th className="table-header">Valor nuevo</th>
                    <th className="table-header">IP</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e, i) => (
                    <tr key={e.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                      <td className="table-cell text-xs whitespace-nowrap">{formatDate(e.fecha_accion)}</td>
                      <td className="table-cell text-xs font-medium">
                        {e.usuario_username ?? <span className="text-gray-400 font-mono">{e.usuario_id.slice(0, 8)}...</span>}
                      </td>
                      <td className="table-cell">
                        <span className="font-mono text-xs">{e.entidad}</span>
                        <span className="block text-[10px] text-gray-400 font-mono">{e.entidad_id.slice(0, 8)}...</span>
                      </td>
                      <td className="table-cell">
                        <span className={clsx('text-xs font-semibold px-2 py-0.5 rounded', ACCION_COLORS[e.accion] || 'badge-info')}>
                          {e.accion}
                        </span>
                      </td>
                      <td className="table-cell font-mono text-xs">{e.campo_modificado ?? '—'}</td>
                      <td className="table-cell text-xs text-gray-500 max-w-32 truncate" title={e.valor_anterior ?? ''}>
                        {e.valor_anterior ?? '—'}
                      </td>
                      <td className="table-cell text-xs text-gray-700 max-w-32 truncate" title={e.valor_nuevo ?? ''}>
                        {e.valor_nuevo ?? '—'}
                      </td>
                      <td className="table-cell font-mono text-[10px] text-gray-400">{e.ip_origen}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pages > 1 && <Paginacion page={page} pages={pages} total={total} onChange={setPage} />}
          </>
        )}
      </div>
    </div>
  )
}
