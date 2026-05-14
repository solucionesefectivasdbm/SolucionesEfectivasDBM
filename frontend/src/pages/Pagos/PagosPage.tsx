import { useState, useEffect, useCallback } from 'react'
import { pagosApi, receptoresApi, creditosApi, gestoresApi } from '@/api'
import { formatCOP, formatFecha, MESES, MOMENTOS, aniosDisponibles } from '@/utils/formatters'
import { LoadingPage, EmptyState, Paginacion, PagoBadge, ConfirmarCreacion, type ItemConfirmacion } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { usePermissions } from '@/store/authStore'
import type { Pago, Receptor, Credito, Gestor } from '@/types'
import { Check, Calendar, User, Plus, Search, DollarSign, CalendarDays, ArrowLeft, RotateCcw } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'

interface PagosPageProps {
  variante?: 'regular' | 'semanal'
}

export default function PagosPage({ variante = 'regular' }: PagosPageProps) {
  const perms = usePermissions()
  const hoy = new Date()
  const navigate = useNavigate()
  const esSemanal = variante === 'semanal'

  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [momento, setMomento] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [filtroGestor, setFiltroGestor] = useState('')
  const [gestores, setGestores] = useState<Gestor[]>([])
  const [page, setPage] = useState(1)

  const [pagos, setPagos] = useState<Pago[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(false)

  // Modales
  const [pagoSeleccionado, setPagoSeleccionado] = useState<Pago | null>(null)
  const [modalRegistrar, setModalRegistrar] = useState(false)
  const [modalConfirmarRegistrar, setModalConfirmarRegistrar] = useState(false)
  const [modalExcedente, setModalExcedente] = useState(false)
  const [modalFecha, setModalFecha] = useState(false)
  const [modalReceptor, setModalReceptor] = useState(false)
  const [modalConfirmarNoProgramado, setModalConfirmarNoProgramado] = useState(false)
  const [modalTipoValidacion, setModalTipoValidacion] = useState(false)
  const [pagoAValidar, setPagoAValidar] = useState<Pago | null>(null)
  const [excedenteMonto, setExcedenteMonto] = useState(0)
  const [montosTemp, setMontosTemp] = useState({ capital: 0, interes: 0 })
  const [receptores, setReceptores] = useState<Receptor[]>([])

  // Modal pago no programado
  const [modalNoProgramado, setModalNoProgramado] = useState(false)
  const [npCreditoId, setNpCreditoId] = useState('')
  const [npMonto, setNpMonto] = useState('')
  const [npDestino, setNpDestino] = useState<'capital' | 'intereses'>('capital')
  const [npFecha, setNpFecha] = useState(new Date().toISOString().split('T')[0])
  // Búsqueda manual de crédito en el modal de pago no programado
  const [npBusquedaCredito, setNpBusquedaCredito] = useState('')
  const [npCreditoSeleccionado, setNpCreditoSeleccionado] = useState<Credito | null>(null)
  const [npCreditosResultados, setNpCreditosResultados] = useState<Credito[]>([])

  // Form registrar pago
  const [capitalPagado, setCapitalPagado] = useState('')
  const [interesPagado, setInteresPagado] = useState('')
  const [nuevaFecha, setNuevaFecha] = useState('')
  const [nuevoReceptor, setNuevoReceptor] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // En la variante semanal, momento es opcional → filtros siempre completos.
  const filtrosCompletos = esSemanal || momento !== ''

  const cargarPagos = useCallback(async () => {
    if (!filtrosCompletos) return
    setLoading(true)
    try {
      const res = await pagosApi.listar({
        anio,
        mes,
        momento: momento || undefined,
        busqueda,
        page,
        gestor_id: filtroGestor || undefined,
        solo_periodicidad: esSemanal ? 'semanal' : undefined,
        excluir_periodicidad: esSemanal ? undefined : 'semanal',
      })
      setPagos(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch { toast.error('Error al cargar pagos') }
    finally { setLoading(false) }
  }, [anio, mes, momento, busqueda, page, filtroGestor, filtrosCompletos, esSemanal])

  useEffect(() => { cargarPagos() }, [cargarPagos])

  useEffect(() => {
    gestoresApi.listar({ page: 1 }).then(r => setGestores(r.data.items)).catch(() => {})
  }, [])

  useEffect(() => {
    if (modalReceptor) {
      receptoresApi.listar().then(r => setReceptores(r.data.items)).catch(() => {})
    }
  }, [modalReceptor])

  const isVencido = (p: Pago) => !p.pagado && new Date(p.fecha_maxima) < new Date()

  const handleSolicitarRegistrar = () => {
    // Antes de registrar, mostrar confirmación con los montos
    setModalRegistrar(false)
    setModalConfirmarRegistrar(true)
  }

  const handleVolverRegistrar = () => {
    setModalConfirmarRegistrar(false)
    setModalRegistrar(true)
  }

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
        setModalConfirmarRegistrar(false)
        setModalExcedente(true)
      } else {
        toast.success(res.data.mensaje)
        setModalConfirmarRegistrar(false)
        cargarPagos()
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al registrar pago')
    } finally { setSubmitting(false) }
  }

  const itemsRegistrar = (): ItemConfirmacion[] => {
    if (!pagoSeleccionado) return []
    const cap = parseFloat(capitalPagado) || 0
    const inter = parseFloat(interesPagado) || 0
    return [
      { label: 'Cuota', value: `#${pagoSeleccionado.numero_cuota}` },
      { label: 'Cliente', value: pagoSeleccionado.cliente_nombre || '—' },
      { label: 'Crédito', value: pagoSeleccionado.numero_credito_cliente || '—' },
      { label: 'Monto esperado', value: formatCOP(pagoSeleccionado.monto_a_pagar) },
      { label: 'Capital a registrar', value: formatCOP(cap) },
      { label: 'Interés a registrar', value: formatCOP(inter) },
      { label: 'Total a registrar', value: formatCOP(cap + inter) },
    ]
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

  const abrirValidar = (pago: Pago) => {
    setPagoAValidar(pago)
    setModalTipoValidacion(true)
  }

  const handleValidar = async (tipo: 'completo' | 'incompleto' | 'con_excedente') => {
    if (!pagoAValidar) return
    try {
      await pagosApi.validar(pagoAValidar.id, tipo)
      toast.success('Pago validado')
      setModalTipoValidacion(false)
      setPagoAValidar(null)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    }
  }

  const handleDesvalidar = async (pago: Pago) => {
    if (!confirm(`¿Revertir el check de la cuota #${pago.numero_cuota} de ${pago.cliente_nombre}?`)) return
    try {
      await pagosApi.desvalidar(pago.id)
      toast.success('Check revertido')
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

  const abrirNoProgramado = () => {
    setNpCreditoId('')
    setNpCreditoSeleccionado(null)
    setNpBusquedaCredito('')
    setNpCreditosResultados([])
    setNpMonto('')
    setNpDestino('capital')
    setNpFecha(new Date().toISOString().split('T')[0])
    setModalNoProgramado(true)
  }

  // Búsqueda manual de créditos en el modal de pago no programado.
  useEffect(() => {
    if (!modalNoProgramado || npCreditoSeleccionado || !npBusquedaCredito.trim()) {
      setNpCreditosResultados([])
      return
    }
    let cancelado = false
    creditosApi.listar({ solo_activos: true, page: 1, busqueda: npBusquedaCredito })
      .then(r => { if (!cancelado) setNpCreditosResultados(r.data.items) })
      .catch(() => { if (!cancelado) setNpCreditosResultados([]) })
    return () => { cancelado = true }
  }, [npBusquedaCredito, modalNoProgramado, npCreditoSeleccionado])

  const handleSolicitarNoProgramado = () => {
    if (!npCreditoId || !npMonto) return
    setModalNoProgramado(false)
    setModalConfirmarNoProgramado(true)
  }

  const handleVolverNoProgramado = () => {
    setModalConfirmarNoProgramado(false)
    setModalNoProgramado(true)
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
      setModalConfirmarNoProgramado(false)
      cargarPagos()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  const itemsNoProgramado = (): ItemConfirmacion[] => {
    return [
      { label: 'Crédito', value: npCreditoSeleccionado ? npCreditoSeleccionado.numero_credito_cliente : '—' },
      { label: 'Monto', value: formatCOP(parseFloat(npMonto) || 0) },
      { label: 'Destino', value: npDestino === 'capital' ? 'Abonar a capital' : 'Abonar a intereses' },
      { label: 'Fecha del pago', value: npFecha },
    ]
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-black text-primary-600">
          {esSemanal ? 'Pagos Semanales' : 'Módulo de Pagos'}
        </h1>
        <div className="flex items-center gap-2">
          {esSemanal ? (
            <button onClick={() => navigate('/pagos')} className="btn-ghost flex items-center gap-2">
              <ArrowLeft size={16} /> Volver a Pagos
            </button>
          ) : (
            <button onClick={() => navigate('/pagos/semanales')} className="btn-secondary flex items-center gap-2">
              <CalendarDays size={16} /> Pagos Semanales
            </button>
          )}
          {perms.canRegistrarPago && (
            <button onClick={abrirNoProgramado} className="btn-primary flex items-center gap-2">
              <DollarSign size={16} /> Pago No Programado
            </button>
          )}
        </div>
      </div>

      {/* Filtros */}
      <div className="card">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
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
            <label className="label">Momento {esSemanal ? '' : '*'}</label>
            <select className="input" value={momento} onChange={e => { setMomento(e.target.value); setPage(1) }}>
              <option value="">{esSemanal ? 'Todos los del mes' : '-- Seleccionar --'}</option>
              {MOMENTOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Gestor</label>
            <select className="input" value={filtroGestor}
              onChange={e => { setFiltroGestor(e.target.value); setPage(1) }}>
              <option value="">Todos</option>
              {gestores.map(g => <option key={g.id} value={g.id}>{g.nombre} {g.apellidos}</option>)}
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
          <p className="font-medium">
            {esSemanal
              ? 'Selecciona año y mes para ver los pagos semanales.'
              : 'Selecciona año, mes y momento para ver los pagos.'}
          </p>
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
                          p.es_proyectada
                            ? 'bg-gray-50 text-gray-400'
                            : i % 2 === 0 ? 'table-row-even' : 'table-row-odd',
                          !p.es_proyectada && isVencido(p) && 'bg-red-50',
                          p.es_ultimo_pago && 'border-l-4 border-l-accent',
                        )}
                        title={p.es_proyectada ? `Proyectada — ${p.razon_bloqueo ?? ''}` : undefined}
                      >
                        <td className="table-cell font-mono font-semibold">
                          {p.es_proyectada && <span className="mr-1">🔒</span>}
                          #{p.numero_cuota}
                        </td>
                        <td className={clsx('table-cell font-medium', p.es_proyectada ? 'text-gray-500' : 'text-gray-800')}>
                          {p.cliente_nombre || '—'}
                        </td>
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
                          {p.es_proyectada ? (
                            <span className="badge-warning" title={p.razon_bloqueo ?? ''}>Bloqueada</span>
                          ) : (
                            <PagoBadge pagado={p.pagado} validado={p.validado_recaudador} />
                          )}
                          {!p.es_proyectada && p.tipo_validacion && (
                            <span
                              className={clsx(
                                'ml-1 text-xs px-2 py-0.5 rounded-full font-medium',
                                p.tipo_validacion === 'completo' && 'bg-green-100 text-green-700',
                                p.tipo_validacion === 'incompleto' && 'bg-yellow-100 text-yellow-700',
                                p.tipo_validacion === 'con_excedente' && 'bg-blue-100 text-blue-700',
                              )}
                            >
                              {p.tipo_validacion === 'con_excedente' ? 'Con excedente' :
                                p.tipo_validacion.charAt(0).toUpperCase() + p.tipo_validacion.slice(1)}
                            </span>
                          )}
                          {!p.es_proyectada && isVencido(p) && <span className="badge-danger ml-1">Vencido</span>}
                          {p.es_ultimo_pago && <span className="badge-warning ml-1">Última</span>}
                        </td>
                        <td className="table-cell">
                          <div className="flex items-center gap-1">
                            {p.es_proyectada && (
                              <span className="text-xs text-gray-400 italic">{p.razon_bloqueo}</span>
                            )}
                            {/* Paso 1: Validar (check) — Recaudador/Admin primero */}
                            {!p.es_proyectada && perms.canValidarPago && !p.pagado && !p.validado_recaudador && (
                              <button
                                title="Validar pago (check)"
                                onClick={() => abrirValidar(p)}
                                className="p-1.5 bg-success text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <Check size={14} />
                              </button>
                            )}
                            {/* Revertir check — visible si está validado y no pagado.
                                Backend valida que no haya montos registrados. */}
                            {!p.es_proyectada && perms.canValidarPago && !p.pagado && p.validado_recaudador && (
                              <button
                                title="Revertir check"
                                onClick={() => handleDesvalidar(p)}
                                className="p-1.5 bg-orange-500 text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <RotateCcw size={14} />
                              </button>
                            )}
                            {/* Paso 2: Registrar montos — Solo si ya fue validado */}
                            {!p.es_proyectada && perms.canRegistrarPago && !p.pagado && p.validado_recaudador && (
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
                            {!p.es_proyectada && perms.canValidarPago && !p.pagado && (
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
                            {!p.es_proyectada && perms.canValidarPago && (
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
              <button onClick={handleSolicitarRegistrar} disabled={submitting} className="btn-primary">
                Continuar
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Modal: Confirmar registro de pago */}
      <Modal isOpen={modalConfirmarRegistrar} onClose={handleVolverRegistrar} title="Confirmar registro de pago">
        <ConfirmarCreacion
          mensaje="Verifique los montos a registrar antes de confirmar."
          items={itemsRegistrar()}
          onConfirmar={handleRegistrar}
          onVolver={handleVolverRegistrar}
          loading={submitting}
          textoConfirmar="Confirmar y registrar"
        />
      </Modal>

      {/* Modal: Tipo de validación */}
      <Modal isOpen={modalTipoValidacion} onClose={() => { setModalTipoValidacion(false); setPagoAValidar(null) }}
        title="Validar pago" size="md">
        {pagoAValidar && (
          <div className="space-y-4">
            <div className="bg-primary-50 rounded-lg p-3 text-sm">
              <p className="font-semibold text-primary-700">
                Cuota #{pagoAValidar.numero_cuota} — {pagoAValidar.cliente_nombre}
              </p>
              <p className="text-gray-600">
                Monto esperado: <strong>{formatCOP(pagoAValidar.monto_a_pagar)}</strong>
              </p>
            </div>
            <p className="text-sm text-gray-600">
              ¿Cómo fue este pago? Esta información ayuda al registrador a saber qué montos esperar.
            </p>
            <div className="grid grid-cols-1 gap-2">
              <button onClick={() => handleValidar('completo')}
                className="px-4 py-3 bg-green-100 text-green-700 hover:bg-green-200 rounded-lg font-medium text-left transition-colors">
                <span className="block font-semibold">Completo</span>
                <span className="block text-xs text-green-600">El cliente pagó exactamente el monto esperado</span>
              </button>
              <button onClick={() => handleValidar('incompleto')}
                className="px-4 py-3 bg-yellow-100 text-yellow-700 hover:bg-yellow-200 rounded-lg font-medium text-left transition-colors">
                <span className="block font-semibold">Incompleto</span>
                <span className="block text-xs text-yellow-600">El cliente pagó menos del monto esperado</span>
              </button>
              <button onClick={() => handleValidar('con_excedente')}
                className="px-4 py-3 bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg font-medium text-left transition-colors">
                <span className="block font-semibold">Con excedente</span>
                <span className="block text-xs text-blue-600">El cliente pagó más del monto esperado</span>
              </button>
            </div>
            <div className="flex justify-end pt-1">
              <button onClick={() => { setModalTipoValidacion(false); setPagoAValidar(null) }}
                className="btn-ghost">
                Cancelar
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
            <div className="relative">
              <input
                type="text"
                className="input"
                placeholder="Escriba para buscar crédito o cliente..."
                value={npCreditoSeleccionado
                  ? `${npCreditoSeleccionado.numero_credito_cliente} — ${formatCOP(npCreditoSeleccionado.saldo_capital)}`
                  : npBusquedaCredito}
                onChange={e => {
                  setNpBusquedaCredito(e.target.value)
                  setNpCreditoSeleccionado(null)
                  setNpCreditoId('')
                }}
                onFocus={() => {
                  if (npCreditoSeleccionado) {
                    setNpBusquedaCredito('')
                    setNpCreditoSeleccionado(null)
                    setNpCreditoId('')
                  }
                }}
              />
              {!npCreditoSeleccionado && npBusquedaCredito && npCreditosResultados.length > 0 && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
                  {npCreditosResultados.map(c => (
                    <button key={c.id} type="button"
                      className="w-full text-left px-3 py-2 text-sm hover:bg-primary-50 border-b border-gray-50 last:border-0"
                      onClick={() => {
                        setNpCreditoSeleccionado(c)
                        setNpCreditoId(c.id)
                        setNpBusquedaCredito('')
                      }}>
                      <span className="font-medium font-mono text-primary-600">{c.numero_credito_cliente}</span>
                      <span className="text-gray-400 ml-2">— saldo {formatCOP(c.saldo_capital)}</span>
                    </button>
                  ))}
                </div>
              )}
              {!npCreditoSeleccionado && npBusquedaCredito && npCreditosResultados.length === 0 && (
                <div className="absolute z-10 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg px-3 py-2 text-sm text-gray-400">
                  Sin resultados
                </div>
              )}
            </div>
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
            <button onClick={handleSolicitarNoProgramado} disabled={!npCreditoId || !npMonto} className="btn-primary">
              Continuar
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Confirmar pago no programado */}
      <Modal isOpen={modalConfirmarNoProgramado} onClose={handleVolverNoProgramado} title="Confirmar pago no programado">
        <ConfirmarCreacion
          mensaje="Verifique los datos del pago no programado antes de registrarlo."
          items={itemsNoProgramado()}
          onConfirmar={handleNoProgramado}
          onVolver={handleVolverNoProgramado}
          loading={submitting}
          textoConfirmar="Confirmar y registrar"
        />
      </Modal>
    </div>
  )
}
