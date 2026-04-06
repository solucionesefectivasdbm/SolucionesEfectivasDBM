import { useState, useEffect, useCallback } from 'react'
import { pagosApi, receptoresApi, creditosApi } from '@/api'
import { formatCOP, formatFecha, MESES, MOMENTOS, aniosDisponibles } from '@/utils/formatters'
import { LoadingPage, EmptyState, Paginacion, PagoBadge } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { usePermissions } from '@/store/authStore'
import type { Pago, Receptor, Credito } from '@/types'
import { Check, Calendar, User, Plus, Search, DollarSign } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

export default function PagosPage() {
  const perms = usePermissions()
  const hoy = new Date()

  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [momento, setMomento] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [page, setPage] = useState(1)

  const [pagos, setPagos] = useState<Pago[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(false)

  // Modales
  const [pagoSeleccionado, setPagoSeleccionado] = useState<Pago | null>(null)
  const [modalRegistrar, setModalRegistrar] = useState(false)
  const [modalExcedente, setModalExcedente] = useState(false)
  const [modalFecha, setModalFecha] = useState(false)
  const [modalReceptor, setModalReceptor] = useState(false)
  const [excedenteMonto, setExcedenteMonto] = useState(0)
  const [montosTemp, setMontosTemp] = useState({ capital: 0, interes: 0 })
  const [receptores, setReceptores] = useState<Receptor[]>([])

  // Modal pago no programado
  const [modalNoProgramado, setModalNoProgramado] = useState(false)
  const [npCreditoId, setNpCreditoId] = useState('')
  const [npMonto, setNpMonto] = useState('')
  const [npDestino, setNpDestino] = useState<'capital' | 'intereses'>('capital')
  const [npFecha, setNpFecha] = useState(new Date().toISOString().split('T')[0])
  const [creditosActivos, setCreditosActivos] = useState<Credito[]>([])

  // Form registrar pago
  const [capitalPagado, setCapitalPagado] = useState('')
  const [interesPagado, setInteresPagado] = useState('')
  const [nuevaFecha, setNuevaFecha] = useState('')
  const [nuevoReceptor, setNuevoReceptor] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const filtrosCompletos = momento !== ''

  const cargarPagos = useCallback(async () => {
    if (!filtrosCompletos) return
    setLoading(true)
    try {
      const res = await pagosApi.listar({ anio, mes, momento, busqueda, page })
      setPagos(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch { toast.error('Error al cargar pagos') }
    finally { setLoading(false) }
  }, [anio, mes, momento, busqueda, page, filtrosCompletos])

  useEffect(() => { cargarPagos() }, [cargarPagos])

  useEffect(() => {
    if (modalReceptor) {
      receptoresApi.listar().then(r => setReceptores(r.data.items)).catch(() => {})
    }
  }, [modalReceptor])

  const isVencido = (p: Pago) => !p.pagado && new Date(p.fecha_maxima) < new Date()

  const handleRegistrar = async () => {
    if (!pagoSeleccionado) return
    setSubmitting(true)
    try {
      const res = await pagosApi.registrar(pagoSeleccionado.id, {
        capital_pagado: parseFloat(capitalPagado) || 0,
        interes_pagado: parseFloat(interesPagado) || 0,
      })
      if (res.data.requiere_decision) {
        setExcedenteMonto(res.data.excedente!)
        setMontosTemp({
          capital: parseFloat(capitalPagado) || 0,
          interes: parseFloat(interesPagado) || 0,
        })
        setModalRegistrar(false)
        setModalExcedente(true)
      } else {
        toast.success(res.data.mensaje)
        setModalRegistrar(false)
        cargarPagos()
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al registrar pago')
    } finally { setSubmitting(false) }
  }

  const handleConfirmarExcedente = async (destino: 'capital' | 'intereses') => {
    if (!pagoSeleccionado) return
    setSubmitting(true)
    try {
      const res = await pagosApi.confirmarExcedente(
        pagoSeleccionado.id,
        { 
          capital_pagado: montosTemp.capital, 
          interes_pagado: montosTemp.interes 
        },
        destino
      )
      toast.success(res.data.mensaje)
      setModalExcedente(false)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { 
      setSubmitting(false) 
    }
  }

  const handleValidar = async (pago: Pago) => {
    try {
      await pagosApi.validar(pago.id)
      toast.success('Pago validado')
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    }
  }

  const handleModificarFecha = async () => {
    if (!pagoSeleccionado || !nuevaFecha) return
    setSubmitting(true)
    try {
      await pagosApi.modificarFecha(pagoSeleccionado.id, nuevaFecha)
      toast.success('Fecha actualizada')
      setModalFecha(false)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  const handleModificarReceptor = async () => {
    if (!pagoSeleccionado || !nuevoReceptor) return
    setSubmitting(true)
    try {
      await pagosApi.modificarReceptor(pagoSeleccionado.id, nuevoReceptor)
      toast.success('Receptor actualizado')
      setModalReceptor(false)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  const abrirNoProgramado = async () => {
    try {
      const res = await creditosApi.listar({ solo_activos: true, page: 1 })
      setCreditosActivos(res.data.items)
      setNpCreditoId('')
      setNpMonto('')
      setNpDestino('capital')
      setNpFecha(new Date().toISOString().split('T')[0])
      setModalNoProgramado(true)
    } catch { toast.error('Error al cargar créditos') }
  }

  const handleNoProgramado = async () => {
    if (!npCreditoId || !npMonto) return
    setSubmitting(true)
    try {
      await pagosApi.noProgramado(npCreditoId, {
        monto: parseFloat(npMonto),
        destino: npDestino,
        fecha_pago: npFecha,
      })
      toast.success('Pago no programado registrado')
      setModalNoProgramado(false)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Módulo de Pagos</h1>
        {perms.canRegistrarPago && (
          <button onClick={abrirNoProgramado} className="btn-primary flex items-center gap-2">
            <DollarSign size={16} /> Pago No Programado
          </button>
        )}
      </div>

      {/* Filtros */}
      <div className="card">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div>
            <label className="label">Año *</label>
            <select className="input" value={anio} onChange={e => { setAnio(+e.target.value); setPage(1) }}>
              {aniosDisponibles().map(a => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Mes *</label>
            <select className="input" value={mes} onChange={e => { setMes(+e.target.value); setPage(1) }}>
              {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Momento *</label>
            <select className="input" value={momento} onChange={e => { setMomento(e.target.value); setPage(1) }}>
              <option value="">-- Seleccionar --</option>
              {MOMENTOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div className="md:col-span-2">
            <label className="label">Buscar cliente</label>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                className="input pl-9"
                placeholder="Nombre del cliente..."
                value={busqueda}
                onChange={e => { setBusqueda(e.target.value); setPage(1) }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Aviso filtros */}
      {!filtrosCompletos && (
        <div className="card text-center py-12 text-gray-400">
          <p className="text-4xl mb-3">🔍</p>
          <p className="font-medium">Selecciona año, mes y momento para ver los pagos.</p>
        </div>
      )}

      {/* Tabla */}
      {filtrosCompletos && (
        <div className="card p-0 overflow-hidden">
          {loading ? <LoadingPage /> : pagos.length === 0 ? (
            <EmptyState message="No hay pagos para el período seleccionado" />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="table-header">Cuota</th>
                      <th className="table-header">Cliente</th>
                      <th className="table-header">Crédito</th>
                      <th className="table-header">Tipo</th>
                      <th className="table-header">Monto</th>
                      <th className="table-header">Capital</th>
                      <th className="table-header">Interés</th>
                      <th className="table-header">Fecha Máx.</th>
                      <th className="table-header">Momento</th>
                      <th className="table-header">Estado</th>
                      <th className="table-header">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagos.map((p, i) => (
                      <tr
                        key={p.id}
                        className={clsx(
                          i % 2 === 0 ? 'table-row-even' : 'table-row-odd',
                          isVencido(p) && 'bg-red-50',
                          p.es_ultimo_pago && 'border-l-4 border-l-accent',
                        )}
                      >
                        <td className="table-cell font-mono font-semibold">#{p.numero_cuota}</td>
                        <td className="table-cell font-medium text-gray-800">{p.cliente_nombre || '—'}</td>
                        <td className="table-cell font-mono text-xs text-gray-500">{p.numero_credito_cliente || p.credito_id.slice(0, 8) + '...'}</td>
                        <td className="table-cell">
                          <span className="badge-info capitalize">{p.tipo_cuota.replace('_', ' ')}</span>
                        </td>
                        <td className="table-cell font-semibold text-primary-600">{formatCOP(p.monto_a_pagar)}</td>
                        <td className="table-cell text-gray-600">{formatCOP(p.capital_a_pagar)}</td>
                        <td className="table-cell text-gray-600">{formatCOP(p.interes_a_pagar)}</td>
                        <td className="table-cell">
                          <span className={clsx('text-xs', isVencido(p) && 'text-danger font-bold')}>
                            {formatFecha(p.fecha_maxima)}
                          </span>
                        </td>
                        <td className="table-cell">
                          <span className="font-mono text-xs bg-primary-100 text-primary-700 px-2 py-0.5 rounded">
                            {p.momento.toUpperCase()}
                          </span>
                        </td>
                        <td className="table-cell">
                          <PagoBadge pagado={p.pagado} validado={p.validado_recaudador} />
                          {isVencido(p) && <span className="badge-danger ml-1">Vencido</span>}
                          {p.es_ultimo_pago && <span className="badge-warning ml-1">Última</span>}
                        </td>
                        <td className="table-cell">
                          <div className="flex items-center gap-1">
                            {/* Paso 1: Validar (check) — Recaudador/Admin primero */}
                            {perms.canValidarPago && !p.pagado && !p.validado_recaudador && (
                              <button
                                title="Validar pago (check)"
                                onClick={() => handleValidar(p)}
                                className="p-1.5 bg-success text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <Check size={14} />
                              </button>
                            )}
                            {/* Paso 2: Registrar montos — Solo si ya fue validado */}
                            {perms.canRegistrarPago && !p.pagado && p.validado_recaudador && (
                              <button
                                title="Registrar pago"
                                onClick={() => {
                                  setPagoSeleccionado(p)
                                  setCapitalPagado(String(p.capital_a_pagar))
                                  setInteresPagado(String(p.interes_a_pagar))
                                  setModalRegistrar(true)
                                }}
                                className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors"
                              >
                                <Plus size={14} />
                              </button>
                            )}
                            {/* Modificar fecha */}
                            {perms.canValidarPago && !p.pagado && (
                              <button
                                title="Modificar fecha"
                                onClick={() => {
                                  setPagoSeleccionado(p)
                                  setNuevaFecha(p.fecha_maxima)
                                  setModalFecha(true)
                                }}
                                className="p-1.5 bg-yellow-500 text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <Calendar size={14} />
                              </button>
                            )}
                            {/* Modificar receptor */}
                            {perms.canValidarPago && (
                              <button
                                title="Modificar receptor"
                                onClick={() => {
                                  setPagoSeleccionado(p)
                                  setNuevoReceptor(p.receptor_id ?? '')
                                  setModalReceptor(true)
                                }}
                                className="p-1.5 bg-gray-500 text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <User size={14} />
                              </button>
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
      )}

      {/* Modal: Registrar pago */}
      <Modal isOpen={modalRegistrar} onClose={() => setModalRegistrar(false)} title="Registrar Pago">
        {pagoSeleccionado && (
          <div className="space-y-4">
            <div className="bg-primary-50 rounded-lg p-3 text-sm">
              <p className="font-semibold text-primary-700">Cuota #{pagoSeleccionado.numero_cuota}</p>
              <p className="text-gray-600">Monto esperado: <strong>{formatCOP(pagoSeleccionado.monto_a_pagar)}</strong></p>
            </div>
            <div>
              <label className="label">Capital pagado</label>
              <input type="number" className="input" value={capitalPagado}
                onChange={e => setCapitalPagado(e.target.value)} />
            </div>
            <div>
              <label className="label">Interés pagado</label>
              <input type="number" className="input" value={interesPagado}
                onChange={e => setInteresPagado(e.target.value)} />
            </div>
            <div className="bg-gray-50 rounded-lg p-2 text-sm text-right font-semibold text-primary-700">
              Total: {formatCOP((parseFloat(capitalPagado) || 0) + (parseFloat(interesPagado) || 0))}
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setModalRegistrar(false)} className="btn-ghost">Cancelar</button>
              <button onClick={handleRegistrar} disabled={submitting} className="btn-primary">
                {submitting ? 'Registrando...' : 'Registrar'}
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal: Excedente (bloqueante) */}
      <Modal isOpen={modalExcedente} title="Decisión de Excedente" closable={false}>
        <div className="space-y-4">
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-center">
            <p className="text-yellow-800 font-semibold text-lg">{formatCOP(excedenteMonto)}</p>
            <p className="text-yellow-700 text-sm">de excedente detectado</p>
          </div>
          <p className="text-sm text-gray-600 text-center">
            ¿A dónde desea aplicar el excedente?
          </p>
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => handleConfirmarExcedente('capital')}
              disabled={submitting}
              className="btn-secondary py-3"
            >
              Reducir Capital
            </button>
            <button
              onClick={() => handleConfirmarExcedente('intereses')}
              disabled={submitting}
              className="btn-primary py-3"
            >
              Reducir Intereses
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Modificar fecha */}
      <Modal isOpen={modalFecha} onClose={() => setModalFecha(false)} title="Modificar Fecha Máxima">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Esta modificación solo afecta este pago individual, no los siguientes.
          </p>
          <div>
            <label className="label">Nueva fecha máxima</label>
            <input type="date" className="input" value={nuevaFecha}
              onChange={e => setNuevaFecha(e.target.value)} />
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalFecha(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleModificarFecha} disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Modificar receptor */}
      <Modal isOpen={modalReceptor} onClose={() => setModalReceptor(false)} title="Modificar Receptor">
        <div className="space-y-4">
          <div>
            <label className="label">Receptor</label>
            <select className="input" value={nuevoReceptor} onChange={e => setNuevoReceptor(e.target.value)}>
              <option value="">-- Seleccionar --</option>
              {receptores.map(r => (
                <option key={r.id} value={r.id}>{r.nombre} — {r.cedula}</option>
              ))}
            </select>
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalReceptor(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleModificarReceptor} disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Pago no programado */}
      <Modal isOpen={modalNoProgramado} onClose={() => setModalNoProgramado(false)} title="Pago No Programado">
        <div className="space-y-4">
          <p className="text-sm text-gray-500">
            Registra un pago fuera del cronograma normal. No afecta las cuotas programadas.
          </p>
          <div>
            <label className="label">Crédito *</label>
            <select className="input" value={npCreditoId} onChange={e => setNpCreditoId(e.target.value)}>
              <option value="">-- Seleccionar crédito --</option>
              {creditosActivos.map(c => (
                <option key={c.id} value={c.id}>{c.numero_credito_cliente} — {formatCOP(c.saldo_capital)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Monto *</label>
            <input type="number" className="input" step="1" min="1" value={npMonto}
              onChange={e => setNpMonto(e.target.value)} placeholder="Monto a pagar" />
          </div>
          <div>
            <label className="label">Destino del pago *</label>
            <select className="input" value={npDestino} onChange={e => setNpDestino(e.target.value as 'capital' | 'intereses')}>
              <option value="capital">Abonar a capital</option>
              <option value="intereses">Abonar a intereses</option>
            </select>
          </div>
          <div>
            <label className="label">Fecha del pago</label>
            <input type="date" className="input" value={npFecha}
              onChange={e => setNpFecha(e.target.value)} />
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalNoProgramado(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleNoProgramado} disabled={submitting || !npCreditoId || !npMonto} className="btn-primary">
              {submitting ? 'Registrando...' : 'Registrar Pago'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
