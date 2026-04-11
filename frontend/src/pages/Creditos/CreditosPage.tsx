import { useState, useEffect, useCallback } from 'react'
import { creditosApi, clientesApi } from '@/api'
import { formatCOP, formatFecha, formatPorcentaje } from '@/utils/formatters'
import { LoadingPage, EmptyState, Paginacion, FormField } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { usePermissions } from '@/store/authStore'
import type { Credito, Pago, Cliente } from '@/types'
import { Plus, Eye, Pencil, Search, Trash2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface CreditoForm {
  cliente_id: string; tipo_credito: string; capital_prestado: number
  tasa_interes_mensual: number; fecha_apertura: string; fecha_inicial_pago: string
  periodicidad: string; numero_cuotas: number; calcular_interes_dias_corridos: boolean
  abono_minimo: number
}

interface EditForm { capital_prestado: number; tasa_interes_mensual: number; fecha_pago_activo: string }

export default function CreditosPage() {
  const perms = usePermissions()
  const [creditos, setCreditos] = useState<Credito[]>([])
  const [clientes, setClientes] = useState<Cliente[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalCrear, setModalCrear] = useState(false)
  const [modalEditar, setModalEditar] = useState(false)
  const [modalHistorial, setModalHistorial] = useState(false)
  const [creditoActual, setCreditoActual] = useState<Credito | null>(null)
  const [historial, setHistorial] = useState<Pago[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [soloActivos, setSoloActivos] = useState(true)

  const { register, handleSubmit, watch, reset, formState: { errors } } = useForm<CreditoForm>()
  const { register: regEdit, handleSubmit: handleEdit } = useForm<EditForm>()
  const tipoCreditoWatch = watch('tipo_credito')

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await creditosApi.listar({ page, busqueda, solo_activos: soloActivos })
      setCreditos(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch { toast.error('Error al cargar créditos') }
    finally { setLoading(false) }
  }, [page, busqueda, soloActivos])

  useEffect(() => { cargar() }, [cargar])

  useEffect(() => {
    clientesApi.listar({ page: 1 }).then(r => setClientes(r.data.items)).catch(() => {})
  }, [])

  const abrirHistorial = async (c: Credito) => {
    setCreditoActual(c)
    try {
      const res = await creditosApi.historialCuotas(c.id)
      setHistorial(res.data)
      setModalHistorial(true)
    } catch { toast.error('Error al cargar historial') }
  }

  const onCrear = async (data: CreditoForm) => {
    setSubmitting(true)
    try {
      const payload = {
        ...data,
        capital_prestado: parseFloat(String(data.capital_prestado)),
        tasa_interes_mensual: parseFloat(String(data.tasa_interes_mensual)) / 100,
        numero_cuotas: data.tipo_credito === 'cuota_fija' ? parseInt(String(data.numero_cuotas)) : null,
        abono_minimo: data.tipo_credito === 'abono_capital' && data.abono_minimo
          ? parseFloat(String(data.abono_minimo)) : null,
      }
      await creditosApi.crear(payload)
      toast.success('Crédito creado')
      setModalCrear(false)
      reset()
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al crear crédito')
    } finally { setSubmitting(false) }
  }

  const onEditar = async (data: EditForm) => {
    if (!creditoActual) return
    setSubmitting(true)
    try {
      const payload: any = {}
      if (data.capital_prestado) payload.capital_prestado = parseFloat(String(data.capital_prestado))
      if (data.tasa_interes_mensual) payload.tasa_interes_mensual = parseFloat(String(data.tasa_interes_mensual)) / 100
      if (data.fecha_pago_activo) payload.fecha_pago_activo = data.fecha_pago_activo
      await creditosApi.actualizar(creditoActual.id, payload)
      toast.success('Crédito actualizado')
      setModalEditar(false)
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  const onEliminar = async (c: Credito) => {
    if (!confirm(`¿Eliminar el crédito ${c.numero_credito_cliente}? Esta acción no se puede deshacer.`)) return
    try {
      await creditosApi.eliminar(c.id)
      toast.success('Crédito eliminado')
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      toast.error(Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error al eliminar')
    }
  }

  const TIPO_LABELS: Record<string, string> = { cuota_fija: 'Cuota Fija', abono_capital: 'Abono Capital' }
  const PERIOD_LABELS: Record<string, string> = { mensual: 'Mensual', quincenal: 'Quincenal', semanal: 'Semanal', diario: 'Diario' }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Créditos</h1>
        {perms.canCreate && (
          <button onClick={() => { reset(); setModalCrear(true) }} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Nuevo Crédito
          </button>
        )}
      </div>

      <div className="card flex items-center gap-4">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por cliente..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input type="checkbox" checked={soloActivos} onChange={e => setSoloActivos(e.target.checked)} className="w-4 h-4" />
          Solo activos
        </label>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : creditos.length === 0 ? <EmptyState message="No hay créditos registrados" /> : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="table-header">Número</th>
                    <th className="table-header">Tipo</th>
                    <th className="table-header">Capital</th>
                    <th className="table-header">Saldo Capital</th>
                    <th className="table-header">Tasa</th>
                    <th className="table-header">Periodicidad</th>
                    <th className="table-header">Inicio</th>
                    <th className="table-header">Estado</th>
                    <th className="table-header">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {creditos.map((c, i) => (
                    <tr key={c.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                      <td className="table-cell font-mono text-xs font-semibold text-primary-600">
                        {c.numero_credito_cliente}
                      </td>
                      <td className="table-cell">
                        <span className={clsx('badge-info', c.tipo_credito === 'abono_capital' && 'badge-warning')}>
                          {TIPO_LABELS[c.tipo_credito]}
                        </span>
                      </td>
                      <td className="table-cell font-semibold">{formatCOP(c.capital_prestado)}</td>
                      <td className="table-cell">
                        <span className={c.saldo_capital > 0 ? 'text-danger font-semibold' : 'text-success font-semibold'}>
                          {formatCOP(c.saldo_capital)}
                        </span>
                      </td>
                      <td className="table-cell font-mono">{formatPorcentaje(c.tasa_interes_mensual)}</td>
                      <td className="table-cell">{PERIOD_LABELS[c.periodicidad]}</td>
                      <td className="table-cell">{formatFecha(c.fecha_apertura)}</td>
                      <td className="table-cell">
                        {c.activo
                          ? <span className="badge-success">Activo</span>
                          : <span className="badge-danger">Cerrado</span>}
                      </td>
                      <td className="table-cell">
                        <div className="flex gap-1">
                          <button onClick={() => abrirHistorial(c)}
                            className="p-1.5 bg-primary-100 text-primary-700 rounded-lg hover:bg-primary-200" title="Ver cuotas">
                            <Eye size={13} />
                          </button>
                          {perms.isAdmin && c.activo && (
                            <>
                              <button onClick={() => { setCreditoActual(c); setModalEditar(true) }}
                                className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700" title="Editar">
                                <Pencil size={13} />
                              </button>
                              <button onClick={() => onEliminar(c)}
                                className="p-1.5 bg-red-100 text-red-600 rounded-lg hover:bg-red-200" title="Eliminar">
                                <Trash2 size={13} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Paginacion page={page} pages={pages} total={total} onChange={setPage} />
          </>
        )}
      </div>

      {/* Modal Crear */}
      <Modal isOpen={modalCrear} onClose={() => setModalCrear(false)} title="Nuevo Crédito" size="xl">
        <form onSubmit={handleSubmit(onCrear)} className="grid grid-cols-2 gap-4">
          <FormField label="Cliente" required error={errors.cliente_id?.message}>
            <select {...register('cliente_id', { required: 'Requerido' })} className="input">
              <option value="">-- Seleccionar --</option>
              {clientes.map(c => <option key={c.id} value={c.id}>{c.nombre} {c.apellidos} — {c.cedula}</option>)}
            </select>
          </FormField>
          <FormField label="Tipo de crédito" required>
            <select {...register('tipo_credito', { required: 'Requerido' })} className="input">
              <option value="">-- Seleccionar --</option>
              <option value="cuota_fija">Cuota Fija</option>
              <option value="abono_capital">Abono a Capital</option>
            </select>
          </FormField>
          <FormField label="Capital prestado (COP)" required error={errors.capital_prestado?.message}>
            <input {...register('capital_prestado', {
              required: 'Requerido',
              min: { value: 1, message: 'Debe ser mayor a 0' },
              validate: (v) => Number(v) > 0 || 'Debe ser mayor a 0',
            })}
              type="number" step="1" className={`input ${errors.capital_prestado ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Tasa de interés mensual (%)" required>
            <input {...register('tasa_interes_mensual', { required: 'Requerido', min: 0.01, max: 99 })}
              type="number" step="0.01" placeholder="ej: 3 para 3%" className="input" />
          </FormField>
          <FormField label="Fecha de apertura" required>
            <input {...register('fecha_apertura', { required: 'Requerido' })} type="date" className="input" />
          </FormField>
          <FormField label="Fecha inicial de pago" required>
            <input {...register('fecha_inicial_pago', { required: 'Requerido' })} type="date" className="input" />
          </FormField>
          <FormField label="Periodicidad" required>
            <select {...register('periodicidad', { required: 'Requerido' })} className="input">
              <option value="">-- Seleccionar --</option>
              <option value="mensual">Mensual</option>
              <option value="quincenal">Quincenal</option>
              {tipoCreditoWatch !== 'abono_capital' && (
                <>
                  <option value="semanal">Semanal</option>
                  <option value="diario">Diario</option>
                </>
              )}
            </select>
          </FormField>
          {tipoCreditoWatch === 'cuota_fija' && (
            <FormField label="Número de cuotas" required>
              <input {...register('numero_cuotas', { required: tipoCreditoWatch === 'cuota_fija' })}
                type="number" min={1} className="input" />
            </FormField>
          )}
          {tipoCreditoWatch === 'abono_capital' && (
            <FormField label="Abono mínimo (opcional)">
              <input {...register('abono_minimo')} type="number" step="1" className="input" />
            </FormField>
          )}
          <div className="col-span-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" {...register('calcular_interes_dias_corridos')} className="w-4 h-4" />
              Calcular interés por días corridos (primera cuota)
            </label>
          </div>
          <div className="col-span-2 flex gap-3 justify-end pt-2">
            <button type="button" onClick={() => setModalCrear(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Creando...' : 'Crear Crédito'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal Editar (solo Admin) */}
      <Modal isOpen={modalEditar} onClose={() => setModalEditar(false)} title="Modificar Crédito">
        <form onSubmit={handleEdit(onEditar)} className="space-y-4">
          <p className="text-xs text-gray-500 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            ⚠️ Modificar estos valores recalculará las cuotas futuras del crédito.
          </p>
          <FormField label="Nuevo capital prestado">
            <input {...regEdit('capital_prestado')} type="number" step="1"
              defaultValue={creditoActual?.capital_prestado} className="input" />
          </FormField>
          <FormField label="Nueva tasa mensual (%)">
            <input {...regEdit('tasa_interes_mensual')} type="number" step="0.01"
              defaultValue={creditoActual ? creditoActual.tasa_interes_mensual * 100 : ''} className="input" />
          </FormField>
          <FormField label="Nueva fecha del pago activo">
            <input {...regEdit('fecha_pago_activo')} type="date" className="input" />
          </FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalEditar(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar cambios'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal Historial */}
      <Modal isOpen={modalHistorial} onClose={() => setModalHistorial(false)}
        title={`Historial — ${creditoActual?.numero_credito_cliente}`} size="xl">
        <div className="overflow-x-auto max-h-96">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="table-header">#</th>
                <th className="table-header">Tipo</th>
                <th className="table-header">Monto</th>
                <th className="table-header">Capital</th>
                <th className="table-header">Interés</th>
                <th className="table-header">Pagado</th>
                <th className="table-header">Fecha Máx.</th>
                <th className="table-header">Estado</th>
              </tr>
            </thead>
            <tbody>
              {historial.map((p, i) => (
                <tr key={p.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  <td className="table-cell font-mono">{p.numero_cuota}</td>
                  <td className="table-cell capitalize">{p.tipo_cuota.replace('_', ' ')}</td>
                  <td className="table-cell">{formatCOP(p.monto_a_pagar)}</td>
                  <td className="table-cell">{formatCOP(p.capital_a_pagar)}</td>
                  <td className="table-cell">{formatCOP(p.interes_a_pagar)}</td>
                  <td className="table-cell">{formatCOP(p.capital_pagado + p.interes_pagado)}</td>
                  <td className="table-cell">{formatFecha(p.fecha_maxima)}</td>
                  <td className="table-cell">
                    {p.pagado
                      ? <span className="badge-success">Pagado</span>
                      : <span className="badge-warning">Pendiente</span>}
                    {p.es_ultimo_pago && <span className="badge-warning ml-1">Última</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Modal>
    </div>
  )
}
