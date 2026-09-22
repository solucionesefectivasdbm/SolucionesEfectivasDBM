import { useState, useEffect, useCallback } from 'react'
import { receptoresApi } from '@/api'
import { usePermissions } from '@/store/authStore'
import { LoadingPage, EmptyState, Paginacion, ConfirmDelete, FormField, ConfirmarCreacion, Spinner, type ItemConfirmacion } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import type { Receptor, CuentaBancaria, SaldoReceptor, MovimientoReceptor, TipoMovimiento } from '@/types'
import { formatCOP, formatCuentaBancaria } from '@/utils/formatters'
import { Plus, Pencil, Trash2, Search, CreditCard, Wallet } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'

export default function ReceptoresPage() {
  const perms = usePermissions()
  const [receptores, setReceptores] = useState<Receptor[]>([])
  const [total, setTotal] = useState(0); const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1); const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalForm, setModalForm] = useState(false)
  const [modalConfirmarCrear, setModalConfirmarCrear] = useState(false)
  const [datosPendientes, setDatosPendientes] = useState<any>(null)
  const [modalConfirmarCuenta, setModalConfirmarCuenta] = useState(false)
  const [datosCuentaPendientes, setDatosCuentaPendientes] = useState<any>(null)
  const [modalEliminar, setModalEliminar] = useState(false)
  const [modalCuentas, setModalCuentas] = useState(false)
  const [modalCuenta, setModalCuenta] = useState(false)
  const [editando, setEditando] = useState<Receptor | null>(null)
  const [seleccionado, setSeleccionado] = useState<Receptor | null>(null)
  const [editandoCuenta, setEditandoCuenta] = useState<CuentaBancaria | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Ledger de movimientos (item 9, receiver-cash-balance)
  const [saldosMap, setSaldosMap] = useState<Record<string, SaldoReceptor>>({})
  const [modalMovimientos, setModalMovimientos] = useState(false)
  const [movimientos, setMovimientos] = useState<MovimientoReceptor[]>([])
  const [movLoading, setMovLoading] = useState(false)
  const [movTotal, setMovTotal] = useState(0); const [movPages, setMovPages] = useState(0)
  const [movPage, setMovPage] = useState(1)
  const [tipoMovimiento, setTipoMovimiento] = useState<TipoMovimiento | null>(null)
  const [modalRegistroMovimiento, setModalRegistroMovimiento] = useState(false)
  const [modalConfirmarMovimiento, setModalConfirmarMovimiento] = useState(false)
  const [datosMovimientoPendientes, setDatosMovimientoPendientes] = useState<any>(null)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<any>()
  const { register: regC, handleSubmit: handleC, reset: resetC } = useForm<any>()
  const { register: regM, handleSubmit: handleM, reset: resetM } = useForm<any>()

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await receptoresApi.listar({ page, busqueda })
      setReceptores(res.data.items); setTotal(res.data.total); setPages(res.data.pages)
      const ids = res.data.items.map(r => r.id)
      if (ids.length > 0) {
        try {
          const saldosRes = await receptoresApi.saldos(ids)
          setSaldosMap(prev => ({ ...prev, ...Object.fromEntries(saldosRes.data.map(s => [s.receptor_id, s])) }))
        } catch {}
      }
    } catch {} finally { setLoading(false) }
  }, [page, busqueda])

  useEffect(() => { cargar() }, [cargar])

  const onSubmit = async (data: any) => {
    if (editando) {
      setSubmitting(true)
      try {
        await receptoresApi.actualizar(editando.id, data)
        toast.success('Receptor actualizado')
        setModalForm(false); cargar()
      } catch (e: any) {
        const detail = e.response?.data?.detail
        const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
        toast.error(msg)
      }
      finally { setSubmitting(false) }
      return
    }
    setDatosPendientes(data)
    setModalForm(false)
    setModalConfirmarCrear(true)
  }

  const handleConfirmarCrear = async () => {
    if (!datosPendientes) return
    setSubmitting(true)
    try {
      await receptoresApi.crear(datosPendientes)
      toast.success('Receptor creado')
      setModalConfirmarCrear(false)
      setDatosPendientes(null)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const handleVolverFormulario = () => {
    setModalConfirmarCrear(false)
    setModalForm(true)
  }

  const itemsConfirmacion = (): ItemConfirmacion[] => {
    if (!datosPendientes) return []
    return [
      { label: 'Nombre', value: datosPendientes.nombre },
      { label: 'Cédula', value: datosPendientes.cedula },
      { label: 'Teléfono', value: datosPendientes.telefono },
    ]
  }

  const handleEliminar = async () => {
    if (!seleccionado) return
    setSubmitting(true)
    try {
      await receptoresApi.eliminar(seleccionado.id)
      toast.success('Receptor eliminado'); setModalEliminar(false); cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const onSubmitCuenta = async (data: any) => {
    if (!seleccionado) return
    if (editandoCuenta) {
      setSubmitting(true)
      try {
        await receptoresApi.actualizarCuenta(seleccionado.id, editandoCuenta.id, data)
        toast.success('Cuenta actualizada')
        setModalCuenta(false)
        const res = await receptoresApi.obtener(seleccionado.id)
        setSeleccionado(res.data)
        cargar()
      } catch (e: any) {
        const detail = e.response?.data?.detail
        const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
        toast.error(msg)
      }
      finally { setSubmitting(false) }
      return
    }
    // Crear cuenta — pedir confirmación
    setDatosCuentaPendientes(data)
    setModalCuenta(false)
    setModalConfirmarCuenta(true)
  }

  const handleConfirmarCrearCuenta = async () => {
    if (!seleccionado || !datosCuentaPendientes) return
    setSubmitting(true)
    try {
      await receptoresApi.agregarCuenta(seleccionado.id, datosCuentaPendientes)
      toast.success('Cuenta agregada')
      setModalConfirmarCuenta(false)
      setDatosCuentaPendientes(null)
      const res = await receptoresApi.obtener(seleccionado.id)
      setSeleccionado(res.data)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const handleVolverCuenta = () => {
    setModalConfirmarCuenta(false)
    setModalCuenta(true)
  }

  const handleMarcarPredeterminada = async (cuenta: CuentaBancaria) => {
    if (!seleccionado || submitting) return
    setSubmitting(true)
    try {
      await receptoresApi.marcarPredeterminada(seleccionado.id, cuenta.id)
      toast.success('Cuenta predeterminada actualizada')
      const res = await receptoresApi.obtener(seleccionado.id)
      setSeleccionado(res.data)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const itemsCuenta = (): ItemConfirmacion[] => {
    if (!datosCuentaPendientes) return []
    return [
      { label: 'Entidad bancaria', value: datosCuentaPendientes.entidad_bancaria },
      { label: 'Tipo de cuenta', value: datosCuentaPendientes.tipo_cuenta },
      { label: 'Número de cuenta', value: datosCuentaPendientes.numero_cuenta },
    ]
  }

  // ─── Ledger de movimientos (item 9, receiver-cash-balance) ────────────────

  const formatFechaHora = (d: string) => new Date(d).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short' })

  const cargarMovimientos = async (receptorId: string, pageNum: number) => {
    setMovLoading(true)
    try {
      const res = await receptoresApi.movimientos(receptorId, { page: pageNum, page_size: 10 })
      setMovimientos(res.data.items); setMovTotal(res.data.total); setMovPages(res.data.pages); setMovPage(pageNum)
    } catch {} finally { setMovLoading(false) }
  }

  const abrirMovimientos = (r: Receptor) => {
    setSeleccionado(r)
    setModalMovimientos(true)
    cargarMovimientos(r.id, 1)
  }

  const abrirRegistroMovimiento = (tipo: TipoMovimiento) => {
    setTipoMovimiento(tipo)
    resetM({})
    setModalRegistroMovimiento(true)
  }

  const onSubmitMovimiento = (data: any) => {
    setDatosMovimientoPendientes(data)
    setModalRegistroMovimiento(false)
    setModalConfirmarMovimiento(true)
  }

  const handleVolverRegistroMovimiento = () => {
    setModalConfirmarMovimiento(false)
    setModalRegistroMovimiento(true)
  }

  const handleConfirmarRegistrarMovimiento = async () => {
    if (!seleccionado || !datosMovimientoPendientes || !tipoMovimiento) return
    setSubmitting(true)
    try {
      const { cuenta_bancaria_id, monto, nota } = datosMovimientoPendientes
      const payload = { monto, nota: nota || undefined }
      if (tipoMovimiento === 'salida') {
        await receptoresApi.registrarSalida(seleccionado.id, cuenta_bancaria_id, payload)
      } else {
        await receptoresApi.registrarCorreccion(seleccionado.id, cuenta_bancaria_id, payload)
      }
      toast.success(tipoMovimiento === 'salida' ? 'Salida registrada' : 'Corrección registrada')
      setModalConfirmarMovimiento(false)
      setDatosMovimientoPendientes(null)
      setTipoMovimiento(null)
      const saldoRes = await receptoresApi.saldo(seleccionado.id)
      setSaldosMap(prev => ({ ...prev, [seleccionado.id]: saldoRes.data }))
      await cargarMovimientos(seleccionado.id, 1)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const itemsMovimiento = (): ItemConfirmacion[] => {
    if (!datosMovimientoPendientes || !seleccionado) return []
    const cuenta = seleccionado.cuentas_bancarias.find(c => c.id === datosMovimientoPendientes.cuenta_bancaria_id)
    return [
      { label: 'Tipo', value: tipoMovimiento === 'salida' ? 'Salida' : 'Corrección' },
      { label: 'Cuenta', value: cuenta ? formatCuentaBancaria(cuenta) : '' },
      { label: 'Monto', value: formatCOP(datosMovimientoPendientes.monto) },
      { label: 'Nota', value: datosMovimientoPendientes.nota || '' },
    ]
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Receptores</h1>
        <button onClick={() => { setEditando(null); reset(); setModalForm(true) }} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Nuevo Receptor
        </button>
      </div>

      <div className="card">
        <div className="relative max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por nombre..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : receptores.length === 0 ? <EmptyState message="Sin receptores" /> : (
          <>
            <table className="w-full">
              <thead><tr>
                <th className="table-header">Nombre</th><th className="table-header">Cédula</th>
                <th className="table-header">Teléfono</th><th className="table-header">Cuentas</th>
                <th className="table-header">Saldo</th>
                <th className="table-header">Acciones</th>
              </tr></thead>
              <tbody>
                {receptores.map((r, i) => (
                  <tr key={r.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                    <td className="table-cell font-medium">{r.nombre}</td>
                    <td className="table-cell font-mono text-xs">{r.cedula}</td>
                    <td className="table-cell">{r.telefono}</td>
                    <td className="table-cell">
                      <span className="badge-info">{r.cuentas_bancarias?.length ?? 0} cuenta(s)</span>
                    </td>
                    <td className="table-cell">
                      {saldosMap[r.id] ? (
                        <span className={saldosMap[r.id].saldo_total >= 0 ? 'badge-success' : 'badge-warning'}>
                          {formatCOP(saldosMap[r.id].saldo_total)}
                        </span>
                      ) : <span className="text-gray-300 text-xs">…</span>}
                    </td>
                    <td className="table-cell">
                      <div className="flex gap-1">
                        <button onClick={() => abrirMovimientos(r)}
                          className="p-1.5 bg-green-100 text-green-700 rounded-lg hover:bg-green-200" title="Ver saldo y movimientos">
                          <Wallet size={13} />
                        </button>
                        <button onClick={() => { setSeleccionado(r); setModalCuentas(true) }}
                          className="p-1.5 bg-primary-100 text-primary-700 rounded-lg hover:bg-primary-200" title="Ver cuentas">
                          <CreditCard size={13} />
                        </button>
                        <button onClick={() => { setEditando(r); reset(r); setModalForm(true) }}
                          className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                          <Pencil size={13} />
                        </button>
                        <button onClick={() => { setSeleccionado(r); setModalEliminar(true) }}
                          className="p-1.5 bg-danger text-white rounded-lg hover:opacity-90">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Paginacion page={page} pages={pages} total={total} onChange={setPage} />
          </>
        )}
      </div>

      <Modal isOpen={modalForm} onClose={() => setModalForm(false)} title={editando ? 'Editar Receptor' : 'Nuevo Receptor'}>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField label="Nombre" required><input {...register('nombre', { required: true })} className="input" /></FormField>
          <FormField label="Cédula" required><input {...register('cedula', { required: true, pattern: { value: /^\d{6,10}$/, message: 'Cédula: 6 a 10 dígitos numéricos' } })} className="input" inputMode="numeric" placeholder="Ej: 1234567890" /></FormField>
          <FormField label="Teléfono" required><input {...register('telefono', { required: true, pattern: { value: /^\d{7,10}$/, message: 'Teléfono: 7 a 10 dígitos numéricos' } })} className="input" inputMode="numeric" placeholder="Ej: 3001234567" /></FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalForm(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : editando ? 'Actualizar' : 'Crear'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalCuentas} onClose={() => setModalCuentas(false)}
        title={`Cuentas de ${seleccionado?.nombre}`} size="lg">
        <div className="space-y-3 mb-4">
          {seleccionado?.cuentas_bancarias?.length === 0
            ? <p className="text-center text-gray-400 text-sm py-4">Sin cuentas registradas</p>
            : seleccionado?.cuentas_bancarias?.map(c => (
              <div key={c.id} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
                <div>
                  <p className="text-sm font-semibold flex items-center gap-2">
                    {c.entidad_bancaria}
                    {c.es_predeterminada && <span className="badge-success">Predeterminada</span>}
                  </p>
                  <p className="text-xs text-gray-500">{c.tipo_cuenta} — {c.numero_cuenta}</p>
                </div>
                <div className="flex items-center gap-1">
                  {!c.es_predeterminada && (
                    <button onClick={() => handleMarcarPredeterminada(c)} disabled={submitting}
                      className="btn-secondary text-xs px-2 py-1">
                      Hacer predeterminada
                    </button>
                  )}
                  <button onClick={() => { setEditandoCuenta(c); resetC(c); setModalCuenta(true) }}
                    className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                    <Pencil size={13} />
                  </button>
                </div>
              </div>
            ))
          }
        </div>
        <button onClick={() => { setEditandoCuenta(null); resetC({}); setModalCuenta(true) }}
          className="btn-secondary w-full flex items-center justify-center gap-2">
          <Plus size={15} /> Agregar cuenta
        </button>
      </Modal>

      <Modal isOpen={modalCuenta} onClose={() => setModalCuenta(false)}
        title={editandoCuenta ? 'Editar Cuenta' : 'Nueva Cuenta'} size="sm">
        <form onSubmit={handleC(onSubmitCuenta)} className="space-y-4">
          <FormField label="Entidad bancaria" required>
            <input {...regC('entidad_bancaria', { required: true })} className="input" />
          </FormField>
          <FormField label="Tipo de cuenta" required>
            <select {...regC('tipo_cuenta', { required: true })} className="input">
              <option value="">-- Seleccionar --</option>
              <option value="Ahorros">Ahorros</option>
              <option value="Corriente">Corriente</option>
            </select>
          </FormField>
          <FormField label="Número de cuenta" required>
            <input {...regC('numero_cuenta', { required: true })} className="input" />
          </FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalCuenta(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalConfirmarCrear} onClose={handleVolverFormulario} title="Confirmar nuevo receptor" size="md">
        <ConfirmarCreacion
          mensaje="Verifique los datos del nuevo receptor antes de crearlo."
          items={itemsConfirmacion()}
          onConfirmar={handleConfirmarCrear}
          onVolver={handleVolverFormulario}
          loading={submitting}
        />
      </Modal>

      <Modal isOpen={modalConfirmarCuenta} onClose={handleVolverCuenta} title="Confirmar nueva cuenta" size="md">
        <ConfirmarCreacion
          mensaje="Verifique los datos de la cuenta bancaria antes de agregarla."
          items={itemsCuenta()}
          onConfirmar={handleConfirmarCrearCuenta}
          onVolver={handleVolverCuenta}
          loading={submitting}
          textoConfirmar="Confirmar y agregar"
        />
      </Modal>

      <Modal isOpen={modalMovimientos} onClose={() => setModalMovimientos(false)}
        title={`Saldo y movimientos de ${seleccionado?.nombre}`} size="lg">
        <div className="space-y-4">
          <div className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
            <span className="text-sm font-semibold text-gray-600">Saldo total</span>
            {seleccionado && saldosMap[seleccionado.id] ? (
              <span className={saldosMap[seleccionado.id].saldo_total >= 0 ? 'badge-success' : 'badge-warning'}>
                {formatCOP(saldosMap[seleccionado.id].saldo_total)}
              </span>
            ) : <Spinner size="sm" />}
          </div>

          {seleccionado && saldosMap[seleccionado.id]?.por_cuenta.length ? (
            <div className="space-y-2">
              {saldosMap[seleccionado.id].por_cuenta.map(c => (
                <div key={c.cuenta_bancaria_id} className="flex items-center justify-between text-sm px-3 py-2 border border-gray-100 rounded-lg">
                  <span className="text-gray-600">
                    {c.etiqueta}
                    {c.es_predeterminada && <span className="badge-success ml-2">Predeterminada</span>}
                  </span>
                  <span className={c.saldo >= 0 ? 'font-semibold text-green-700' : 'font-semibold text-yellow-700'}>
                    {formatCOP(c.saldo)}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {perms.isAdmin && (
            <div className="flex gap-2">
              <button onClick={() => abrirRegistroMovimiento('salida')} className="btn-secondary flex-1 text-xs">
                Registrar salida
              </button>
              <button onClick={() => abrirRegistroMovimiento('correccion')} className="btn-secondary flex-1 text-xs">
                Registrar corrección
              </button>
            </div>
          )}

          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Historial</p>
            {movLoading ? (
              <div className="flex justify-center py-6"><Spinner size="sm" /></div>
            ) : movimientos.length === 0 ? (
              <p className="text-center text-gray-400 text-sm py-4">Sin movimientos registrados</p>
            ) : (
              <>
                <table className="w-full text-xs">
                  <thead><tr>
                    <th className="table-header">Tipo</th><th className="table-header">Monto</th>
                    <th className="table-header">Nota</th><th className="table-header">Usuario</th>
                    <th className="table-header">Fecha</th>
                  </tr></thead>
                  <tbody>
                    {movimientos.map((m, i) => (
                      <tr key={m.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                        <td className="table-cell">
                          <span className={m.tipo === 'salida' ? 'badge-warning' : 'badge-info'}>
                            {m.tipo === 'salida' ? 'Salida' : 'Corrección'}
                          </span>
                        </td>
                        <td className="table-cell font-mono">{formatCOP(m.monto)}</td>
                        <td className="table-cell text-gray-500">{m.nota || '—'}</td>
                        <td className="table-cell">{m.usuario_nombre || '—'}</td>
                        <td className="table-cell whitespace-nowrap">{formatFechaHora(m.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Paginacion page={movPage} pages={movPages} total={movTotal}
                  onChange={(p) => seleccionado && cargarMovimientos(seleccionado.id, p)} />
              </>
            )}
          </div>
        </div>
      </Modal>

      <Modal isOpen={modalRegistroMovimiento} onClose={() => setModalRegistroMovimiento(false)}
        title={tipoMovimiento === 'salida' ? 'Registrar salida' : 'Registrar corrección'} size="sm">
        <form onSubmit={handleM(onSubmitMovimiento)} className="space-y-4">
          <FormField label="Cuenta bancaria" required>
            <select {...regM('cuenta_bancaria_id', { required: true })} className="input">
              <option value="">-- Seleccionar --</option>
              {seleccionado?.cuentas_bancarias.map(c => (
                <option key={c.id} value={c.id}>{formatCuentaBancaria(c)}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Monto" required>
            <input
              type="number" step="0.01"
              min={tipoMovimiento === 'salida' ? '0.01' : undefined}
              {...regM('monto', { required: true })}
              className="input"
              placeholder={tipoMovimiento === 'correccion' ? 'Ej: -15000 o 20000' : 'Ej: 300000'}
            />
          </FormField>
          <FormField label="Nota (opcional)">
            <input {...regM('nota')} className="input" maxLength={500} />
          </FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalRegistroMovimiento(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" className="btn-primary">Continuar</button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalConfirmarMovimiento} onClose={handleVolverRegistroMovimiento}
        title={tipoMovimiento === 'salida' ? 'Confirmar salida' : 'Confirmar corrección'} size="md">
        <ConfirmarCreacion
          mensaje={tipoMovimiento === 'salida'
            ? 'Verifique los datos de la salida antes de registrarla. Esta acción no se puede deshacer.'
            : 'Verifique los datos de la corrección antes de registrarla. Esta acción no se puede deshacer.'}
          items={itemsMovimiento()}
          onConfirmar={handleConfirmarRegistrarMovimiento}
          onVolver={handleVolverRegistroMovimiento}
          loading={submitting}
          textoConfirmar={tipoMovimiento === 'salida' ? 'Confirmar y registrar salida' : 'Confirmar y registrar corrección'}
        />
      </Modal>

      <Modal isOpen={modalEliminar} onClose={() => setModalEliminar(false)} title="Eliminar Receptor" size="sm">
        <ConfirmDelete message={`¿Eliminar al receptor ${seleccionado?.nombre}?`}
          onConfirm={handleEliminar} onCancel={() => setModalEliminar(false)} loading={submitting} />
      </Modal>
    </div>
  )
}
