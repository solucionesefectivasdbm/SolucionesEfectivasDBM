import { useState, useEffect, useCallback } from 'react'
import { creditosApi, clientesApi, gestoresApi } from '@/api'
import { formatCOP, formatFecha, formatPorcentaje } from '@/utils/formatters'
import { LoadingPage, EmptyState, Paginacion, FormField, ConfirmarCreacion, type ItemConfirmacion } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { usePermissions } from '@/store/authStore'
import type { Credito, Pago, Cliente, Gestor } from '@/types'
import { Plus, Eye, Pencil, Search, Trash2, CalendarDays } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'
import clsx from 'clsx'

interface CreditoForm {
  cliente_id: string; tipo_credito: string; capital_prestado: number
  tasa_interes_mensual: number; fecha_apertura: string; fecha_inicial_pago: string
  fecha_inicial_pago_2?: string
  periodicidad: string; numero_cuotas: number; calcular_interes_dias_corridos: boolean
  abono_minimo: number
}

interface EditForm {
  capital_prestado: number
  tasa_interes_mensual: number
  abono_minimo: number
}

interface DiasPagoForm {
  anchor_dia_1: number
  anchor_dia_2: number
}

export default function CreditosPage() {
  const perms = usePermissions()
  const [creditos, setCreditos] = useState<Credito[]>([])
  const [clientes, setClientes] = useState<Cliente[]>([])
  const [gestores, setGestores] = useState<Gestor[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [busqueda, setBusqueda] = useState('')
  const [filtroGestor, setFiltroGestor] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalCrear, setModalCrear] = useState(false)
  const [modalConfirmarCrear, setModalConfirmarCrear] = useState(false)
  const [datosPendientes, setDatosPendientes] = useState<CreditoForm | null>(null)
  const [modalEditar, setModalEditar] = useState(false)
  const [modalHistorial, setModalHistorial] = useState(false)
  const [creditoActual, setCreditoActual] = useState<Credito | null>(null)
  const [historial, setHistorial] = useState<Pago[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [soloActivos, setSoloActivos] = useState(true)
  const [busquedaCliente, setBusquedaCliente] = useState('')
  const [clienteSeleccionado, setClienteSeleccionado] = useState<Cliente | null>(null)
  const [modalDiasPago, setModalDiasPago] = useState(false)
  const [creditoDias, setCreditoDias] = useState<Credito | null>(null)

  const { register, handleSubmit, watch, reset, formState: { errors } } = useForm<CreditoForm>()
  const { register: regEdit, handleSubmit: handleEdit, reset: resetEdit } = useForm<EditForm>()
  const { register: regDias, handleSubmit: handleDias, reset: resetDias, formState: { errors: errorsDias } } = useForm<DiasPagoForm>()
  const tipoCreditoWatch = watch('tipo_credito')
  const periodicidadWatch = watch('periodicidad')
  const fechaInicialPagoWatch = watch('fecha_inicial_pago')

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await creditosApi.listar({ page, busqueda, solo_activos: soloActivos, gestor_id: filtroGestor || undefined })
      setCreditos(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch { toast.error('Error al cargar créditos') }
    finally { setLoading(false) }
  }, [page, busqueda, soloActivos, filtroGestor])

  useEffect(() => { cargar() }, [cargar])

  useEffect(() => {
    clientesApi.listar({ page: 1, busqueda: busquedaCliente })
      .then(r => setClientes(r.data.items)).catch(() => {})
  }, [busquedaCliente])

  useEffect(() => {
    gestoresApi.listar({ page: 1 }).then(r => setGestores(r.data.items)).catch(() => {})
  }, [])

  const abrirHistorial = async (c: Credito) => {
    setCreditoActual(c)
    try {
      const res = await creditosApi.historialCuotas(c.id)
      setHistorial(res.data)
      setModalHistorial(true)
    } catch { toast.error('Error al cargar historial') }
  }

  const onCrear = (data: CreditoForm) => {
    // En vez de enviar de inmediato, mostramos el modal de confirmación
    setDatosPendientes(data)
    setModalCrear(false)
    setModalConfirmarCrear(true)
  }

  const handleConfirmarCrear = async () => {
    if (!datosPendientes) return
    setSubmitting(true)
    try {
      const payload = {
        ...datosPendientes,
        capital_prestado: parseFloat(String(datosPendientes.capital_prestado)),
        tasa_interes_mensual: parseFloat(String(datosPendientes.tasa_interes_mensual)) / 100,
        numero_cuotas: datosPendientes.tipo_credito === 'cuota_fija' ? parseInt(String(datosPendientes.numero_cuotas)) : null,
        abono_minimo: datosPendientes.tipo_credito === 'abono_capital' && datosPendientes.abono_minimo
          ? parseFloat(String(datosPendientes.abono_minimo)) : null,
        fecha_inicial_pago_2: datosPendientes.periodicidad === 'quincenal'
          ? (datosPendientes.fecha_inicial_pago_2 || undefined)
          : undefined,
      }
      await creditosApi.crear(payload)
      toast.success('Crédito creado')
      setModalConfirmarCrear(false)
      setDatosPendientes(null)
      setClienteSeleccionado(null)
      reset()
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al crear crédito')
    } finally { setSubmitting(false) }
  }

  const handleVolverFormulario = () => {
    setModalConfirmarCrear(false)
    setModalCrear(true)
  }

  const itemsConfirmacion = (): ItemConfirmacion[] => {
    if (!datosPendientes) return []
    const cliente = clienteSeleccionado
    const tipo = TIPO_LABELS[datosPendientes.tipo_credito] ?? datosPendientes.tipo_credito
    const periodicidad = PERIOD_LABELS[datosPendientes.periodicidad] ?? datosPendientes.periodicidad
    const capital = parseFloat(String(datosPendientes.capital_prestado)) || 0
    const tasa = parseFloat(String(datosPendientes.tasa_interes_mensual)) || 0
    const items: ItemConfirmacion[] = [
      { label: 'Cliente', value: cliente ? `${cliente.nombre} ${cliente.apellidos} — ${cliente.cedula}` : '—' },
      { label: 'Tipo de crédito', value: tipo },
      { label: 'Capital prestado', value: formatCOP(capital) },
      { label: 'Tasa mensual', value: `${tasa}%` },
      { label: 'Fecha de apertura', value: datosPendientes.fecha_apertura },
      { label: 'Fecha inicial de pago', value: datosPendientes.fecha_inicial_pago },
      { label: 'Periodicidad', value: periodicidad },
    ]
    if (datosPendientes.periodicidad === 'quincenal' && datosPendientes.fecha_inicial_pago_2) {
      items.splice(items.findIndex(i => i.label === 'Periodicidad') + 1, 0, {
        label: 'Segunda fecha de pago',
        value: datosPendientes.fecha_inicial_pago_2,
      })
    }
    if (datosPendientes.tipo_credito === 'cuota_fija') {
      items.push({ label: 'Número de cuotas', value: String(datosPendientes.numero_cuotas) })
    }
    if (datosPendientes.tipo_credito === 'abono_capital' && datosPendientes.abono_minimo) {
      items.push({ label: 'Abono mínimo', value: formatCOP(parseFloat(String(datosPendientes.abono_minimo))) })
    }
    items.push({
      label: 'Interés por días corridos',
      value: datosPendientes.calcular_interes_dias_corridos ? 'Sí (primera cuota)' : 'No',
    })
    return items
  }

  const onEditar = async (data: EditForm) => {
    if (!creditoActual) return
    setSubmitting(true)
    try {
      const payload: any = {}
      if (data.capital_prestado) payload.capital_prestado = parseFloat(String(data.capital_prestado))
      if (data.tasa_interes_mensual) payload.tasa_interes_mensual = parseFloat(String(data.tasa_interes_mensual)) / 100
      // abono_minimo solo aplica a abono_capital. Se envía aunque sea 0
      // (puede querer ponerlo en 0), por eso se valida que no sea undefined/'' .
      if (
        creditoActual.tipo_credito === 'abono_capital' &&
        data.abono_minimo !== undefined &&
        String(data.abono_minimo) !== ''
      ) {
        payload.abono_minimo = parseFloat(String(data.abono_minimo))
      }
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

  const onDiasPago = async (data: DiasPagoForm) => {
    if (!creditoDias) return
    setSubmitting(true)
    try {
      const payload: { anchor_dia_1: number; anchor_dia_2?: number } = {
        anchor_dia_1: parseInt(String(data.anchor_dia_1)),
      }
      if (creditoDias.periodicidad === 'quincenal') {
        payload.anchor_dia_2 = parseInt(String(data.anchor_dia_2))
      }
      await creditosApi.actualizarDiasPago(creditoDias.id, payload)
      toast.success('Días de pago actualizados')
      setModalDiasPago(false)
      setCreditoDias(null)
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al actualizar días de pago')
    } finally { setSubmitting(false) }
  }

  const TIPO_LABELS: Record<string, string> = { cuota_fija: 'Cuota Fija', abono_capital: 'Abono Capital' }
  const PERIOD_LABELS: Record<string, string> = { mensual: 'Mensual', quincenal: 'Quincenal', semanal: 'Semanal', diario: 'Diario' }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Créditos</h1>
        {perms.canCreate && (
          <button onClick={() => { reset(); setClienteSeleccionado(null); setBusquedaCliente(''); setModalCrear(true) }} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Nuevo Crédito
          </button>
        )}
      </div>

      <div className="card flex items-center gap-4 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por cliente..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
        <select className="input max-w-[220px]" value={filtroGestor}
          onChange={e => { setFiltroGestor(e.target.value); setPage(1) }}>
          <option value="">Todos los gestores</option>
          {gestores.map(g => <option key={g.id} value={g.id}>{g.nombre} {g.apellidos}</option>)}
        </select>
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
                          {(perms.isAdmin || perms.canCreate || perms.isRecaudador) && c.activo &&
                            (c.periodicidad === 'mensual' || c.periodicidad === 'quincenal') && (
                            <button onClick={() => {
                              setCreditoDias(c)
                              resetDias({
                                anchor_dia_1: c.anchor_dia_1 ?? 1,
                                anchor_dia_2: c.anchor_dia_2 ?? 1,
                              })
                              setModalDiasPago(true)
                            }}
                              className="p-1.5 bg-indigo-100 text-indigo-700 rounded-lg hover:bg-indigo-200" title="Editar días de pago">
                              <CalendarDays size={13} />
                            </button>
                          )}
                          {perms.isAdmin && c.activo && (
                            <>
                              <button onClick={() => {
                                setCreditoActual(c)
                                resetEdit({
                                  capital_prestado: c.capital_prestado,
                                  tasa_interes_mensual: c.tasa_interes_mensual * 100,
                                  abono_minimo: c.abono_minimo ?? 0,
                                })
                                setModalEditar(true)
                              }}
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
            <input type="hidden" {...register('cliente_id', { required: 'Requerido' })} />
            <div className="relative">
              <input
                type="text"
                className="input"
                placeholder="Escriba para buscar cliente..."
                value={clienteSeleccionado ? `${clienteSeleccionado.nombre} ${clienteSeleccionado.apellidos} — ${clienteSeleccionado.cedula}` : busquedaCliente}
                onChange={e => { setBusquedaCliente(e.target.value); setClienteSeleccionado(null); reset({ ...watch(), cliente_id: '' }) }}
                onFocus={() => { if (clienteSeleccionado) { setBusquedaCliente(''); setClienteSeleccionado(null); reset({ ...watch(), cliente_id: '' }) } }}
              />
              {!clienteSeleccionado && busquedaCliente && clientes.length > 0 && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {clientes.map(c => (
                    <button key={c.id} type="button"
                      className="w-full text-left px-3 py-2 text-sm hover:bg-primary-50 border-b border-gray-50 last:border-0"
                      onClick={() => { setClienteSeleccionado(c); setBusquedaCliente(''); reset({ ...watch(), cliente_id: c.id }) }}>
                      <span className="font-medium">{c.nombre} {c.apellidos}</span>
                      <span className="text-gray-400 ml-2">— {c.cedula}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
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
          {periodicidadWatch === 'quincenal' && (
            <FormField label="Segunda fecha de pago" required error={errors.fecha_inicial_pago_2?.message}>
              <input
                {...register('fecha_inicial_pago_2', {
                  required: periodicidadWatch === 'quincenal' ? 'Requerido para quincenal' : false,
                  validate: (v) => {
                    if (periodicidadWatch !== 'quincenal') return true
                    if (!v) return 'Requerido para quincenal'
                    if (fechaInicialPagoWatch && v) {
                      const d1 = new Date(fechaInicialPagoWatch)
                      const d2 = new Date(v)
                      if (d1.getUTCDate() === d2.getUTCDate()) return 'Las dos fechas deben caer en días distintos del mes'
                    }
                    return true
                  },
                })}
                type="date"
                className={`input ${errors.fecha_inicial_pago_2 ? 'input-error' : ''}`}
              />
            </FormField>
          )}
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

      {/* Modal Confirmar creación */}
      <Modal isOpen={modalConfirmarCrear} onClose={handleVolverFormulario} title="Confirmar nuevo crédito" size="lg">
        <ConfirmarCreacion
          mensaje="Verifique que los datos del crédito sean correctos antes de crearlo."
          items={itemsConfirmacion()}
          onConfirmar={handleConfirmarCrear}
          onVolver={handleVolverFormulario}
          loading={submitting}
        />
      </Modal>

      {/* Modal Editar (solo Admin) */}
      <Modal isOpen={modalEditar} onClose={() => setModalEditar(false)} title="Modificar Crédito">
        <form onSubmit={handleEdit(onEditar)} className="space-y-4">
          <p className="text-xs text-gray-500 bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            ⚠️ Modificar estos valores recalculará la cuota actual y las cuotas futuras del crédito.
          </p>
          <FormField label="Nuevo capital prestado">
            <input {...regEdit('capital_prestado')} type="number" step="1"
              defaultValue={creditoActual?.capital_prestado} className="input" />
          </FormField>
          <FormField label="Nueva tasa mensual (%)">
            <input {...regEdit('tasa_interes_mensual')} type="number" step="0.01"
              defaultValue={creditoActual ? creditoActual.tasa_interes_mensual * 100 : ''} className="input" />
          </FormField>
          {creditoActual?.tipo_credito === 'abono_capital' && (
            <FormField label="Nuevo abono mínimo">
              <input {...regEdit('abono_minimo')} type="number" step="1"
                defaultValue={creditoActual?.abono_minimo ?? 0} className="input" />
            </FormField>
          )}
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalEditar(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar cambios'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal Días de Pago */}
      <Modal isOpen={modalDiasPago} onClose={() => { setModalDiasPago(false); setCreditoDias(null) }}
        title="Editar días de pago">
        <form onSubmit={handleDias(onDiasPago)} className="space-y-4">
          <p className="text-xs text-gray-500 bg-blue-50 border border-blue-200 rounded-lg p-3">
            Las cuotas pendientes se reprogramarán a los nuevos días. Los montos no cambian.
          </p>
          <FormField label="Día de pago" required error={errorsDias.anchor_dia_1?.message}>
            <input
              {...regDias('anchor_dia_1', {
                required: 'Requerido',
                min: { value: 1, message: 'Mínimo 1' },
                max: { value: 31, message: 'Máximo 31' },
                valueAsNumber: true,
              })}
              type="number" min={1} max={31}
              className={`input ${errorsDias.anchor_dia_1 ? 'input-error' : ''}`}
            />
          </FormField>
          {creditoDias?.periodicidad === 'quincenal' && (
            <FormField label="Segundo día de pago" required error={errorsDias.anchor_dia_2?.message}>
              <input
                {...regDias('anchor_dia_2', {
                  required: 'Requerido para quincenal',
                  min: { value: 1, message: 'Mínimo 1' },
                  max: { value: 31, message: 'Máximo 31' },
                  valueAsNumber: true,
                  validate: (v, values) =>
                    Number(v) !== Number(values.anchor_dia_1) || 'Los días deben ser distintos',
                })}
                type="number" min={1} max={31}
                className={`input ${errorsDias.anchor_dia_2 ? 'input-error' : ''}`}
              />
            </FormField>
          )}
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => { setModalDiasPago(false); setCreditoDias(null) }} className="btn-ghost">
              Cancelar
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar días'}
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
                <th className="table-header">Cap. pagado</th>
                <th className="table-header">Int. pagado</th>
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
                  <td className="table-cell">{formatCOP(p.capital_pagado)}</td>
                  <td className="table-cell">{formatCOP(p.interes_pagado)}</td>
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
