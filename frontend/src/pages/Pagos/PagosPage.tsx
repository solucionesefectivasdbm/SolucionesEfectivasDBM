import { useState, useEffect, useCallback, useId, useRef } from 'react'
import { pagosApi, receptoresApi, creditosApi, gestoresApi } from '@/api'
import { formatCOP, formatFecha, formatCuentaBancaria, MESES, MOMENTOS, aniosDisponibles } from '@/utils/formatters'
import { LoadingPage, EmptyState, Paginacion, PagoBadge, ConfirmarCreacion, ConfirmarCierreInteresPendiente, ConfirmDelete, type ItemConfirmacion } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import SelectCuentaBancaria from '@/components/ui/SelectCuentaBancaria'
import RepartoPagoModal from '@/components/pagos/RepartoPagoModal'
import { usePermissions } from '@/store/authStore'
import { mensajeError, esErrorSesionExpirada } from '@/utils/apiErrors'
import type { Pago, Receptor, Credito, Gestor } from '@/types'
import { Check, Calendar, User, Plus, Search, DollarSign, CalendarDays, ArrowLeft, RotateCcw, ChevronUp, ChevronDown, X } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'

interface PagosPageProps {
  variante?: 'regular' | 'semanal' | 'diario' | 'aplazados'
}

export default function PagosPage({ variante = 'regular' }: PagosPageProps) {
  const perms = usePermissions()
  const hoy = new Date()
  const navigate = useNavigate()
  const esSemanal = variante === 'semanal'
  const esDiario = variante === 'diario'
  const esAplazados = variante === 'aplazados'

  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [momento, setMomento] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [filtroGestor, setFiltroGestor] = useState('')
  const [filtroReceptor, setFiltroReceptor] = useState('')
  const [filtroReceptorBusqueda, setFiltroReceptorBusqueda] = useState('')
  const [receptorDropdownAbierto, setReceptorDropdownAbierto] = useState(false)
  // Opción resaltada por teclado en el combobox de receptor.
  const [receptorActivoId, setReceptorActivoId] = useState<string | null>(null)
  const idListboxReceptor = `${useId()}-receptores`
  const [filtroCuentaBancaria, setFiltroCuentaBancaria] = useState('')
  const [gestores, setGestores] = useState<Gestor[]>([])
  const [page, setPage] = useState(1)
  const [incluirPagados, setIncluirPagados] = useState(false)

  const [pagos, setPagos] = useState<Pago[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(false)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  // Modales
  const [pagoSeleccionado, setPagoSeleccionado] = useState<Pago | null>(null)
  const [modalRegistrar, setModalRegistrar] = useState(false)
  const [modalConfirmarRegistrar, setModalConfirmarRegistrar] = useState(false)
  const [modalExcedente, setModalExcedente] = useState(false)
  const [modalFecha, setModalFecha] = useState(false)
  const [modalCuentaBancaria, setModalCuentaBancaria] = useState(false)
  // payment-multi-recipient (item 10, PR3): modal de reparto multi-destinatario
  // para pagos YA PAGADOS. Pagos pendientes siguen usando modalCuentaBancaria.
  const [modalReparto, setModalReparto] = useState(false)
  const [modalConfirmarNoProgramado, setModalConfirmarNoProgramado] = useState(false)
  const [modalTipoValidacion, setModalTipoValidacion] = useState(false)
  const [pagoAValidar, setPagoAValidar] = useState<Pago | null>(null)
  const [excedenteMonto, setExcedenteMonto] = useState(0)
  const [montosTemp, setMontosTemp] = useState({ capital: 0, interes: 0 })
  const [receptores, setReceptores] = useState<Receptor[]>([])
  const [receptoresCuenta, setReceptoresCuenta] = useState<Receptor[]>([])

  // Modal pago no programado
  const [modalNoProgramado, setModalNoProgramado] = useState(false)
  const [npCreditoId, setNpCreditoId] = useState('')
  const [creditoCierre, setCreditoCierre] = useState<Credito | null>(null)
  const [cerrandoCreditoCierre, setCerrandoCreditoCierre] = useState(false)
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
  const [esAplazamiento, setEsAplazamiento] = useState(false)
  const [nuevaCuentaBancaria, setNuevaCuentaBancaria] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [pagoADesvalidar, setPagoADesvalidar] = useState<Pago | null>(null)

  // En las variantes semanal, diario y aplazados, momento es opcional (o no
  // aplica) → filtros siempre completos.
  const filtrosCompletos = esSemanal || esDiario || esAplazados || momento !== ''

  const handleSortToggle = () => {
    setSortDir(prev => prev === 'asc' ? 'desc' : 'asc')
    setPage(1)
  }

  // mostrarSpinner=true para carga inicial y cambios de filtro (se quiere el
  // estado de carga). false para recargas tras una acción sobre un pago —
  // así la tabla no se desmonta y la posición de scroll se mantiene, evitando
  // tener que volver a buscar el mismo pago para hacerle otra acción.
  const cargarPagos = useCallback(async (mostrarSpinner = true) => {
    if (!filtrosCompletos) return
    if (mostrarSpinner) setLoading(true)
    try {
      const res = esAplazados
        ? await pagosApi.listarAplazados({
            incluir_pagados: incluirPagados,
            sort_dir: sortDir,
            busqueda,
            page,
            gestor_id: filtroGestor || undefined,
          })
        : await pagosApi.listar({
            anio,
            mes,
            momento: momento || undefined,
            sort_dir: sortDir,
            busqueda,
            page,
            gestor_id: filtroGestor || undefined,
            receptor_id: filtroReceptor || undefined,
            cuenta_bancaria_id: filtroCuentaBancaria || undefined,
            solo_periodicidad: esSemanal ? 'semanal' : esDiario ? 'diario' : undefined,
            excluir_periodicidades: (!esSemanal && !esDiario) ? ['semanal', 'diario'] : undefined,
          })
      setPagos(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch (e: any) { toast.error(e.response?.data?.detail || 'Error al cargar pagos') }
    finally { if (mostrarSpinner) setLoading(false) }
  }, [anio, mes, momento, sortDir, busqueda, page, filtroGestor, filtroReceptor, filtroCuentaBancaria, filtrosCompletos, esSemanal, esDiario, esAplazados, incluirPagados])

  useEffect(() => { cargarPagos() }, [cargarPagos])

  useEffect(() => {
    gestoresApi.listar({ page: 1 }).then(r => setGestores(r.data.items)).catch(() => {})
  }, [])

  // Receptores (con sus cuentas bancarias) para el filtro en cascada
  // (perms.canValidarPago). El backend limita /receptores a 50 resultados,
  // así que se recarga con `busqueda` (debounce 300ms) para que cualquier
  // receptor siga siendo alcanzable.
  useEffect(() => {
    if (!perms.canValidarPago || esAplazados) return
    let cancelado = false
    const timer = setTimeout(() => {
      receptoresApi.listar({ page: 1, busqueda: filtroReceptorBusqueda })
        .then(r => { if (!cancelado) setReceptores(r.data.items) })
        .catch(() => {})
    }, 300)
    return () => { cancelado = true; clearTimeout(timer) }
  }, [perms.canValidarPago, esAplazados, filtroReceptorBusqueda])

  // Receptores para el modal "Modificar cuenta" (lista propia e independiente
  // del filtro en cascada, se recarga solo al abrir el modal; el buscador
  // interno de SelectCuentaBancaria dispara sus propias recargas).
  // Request sequence counter shared by the initial load and the search
  // handler: only the latest response is applied.
  const receptoresCuentaSeqRef = useRef(0)
  useEffect(() => {
    // También se carga para modalReparto (item 10, PR3): RepartoPagoModal
    // reusa esta misma lista + handleBusquedaReceptoresCuenta.
    if (!modalCuentaBancaria && !modalReparto) return
    const seq = ++receptoresCuentaSeqRef.current
    receptoresApi.listar({ page: 1 })
      .then(r => { if (seq === receptoresCuentaSeqRef.current) setReceptoresCuenta(r.data.items) })
      .catch(() => {})
  }, [modalCuentaBancaria, modalReparto])

  const handleBusquedaReceptoresCuenta = useCallback((busqueda: string) => {
    const seq = ++receptoresCuentaSeqRef.current
    receptoresApi.listar({ page: 1, busqueda })
      .then(r => { if (seq === receptoresCuentaSeqRef.current) setReceptoresCuenta(r.data.items) })
      .catch(() => {})
  }, [])

  const handleFiltroReceptorChange = (receptorId: string) => {
    setFiltroReceptor(receptorId)
    setFiltroCuentaBancaria('')
    setPage(1)
  }

  // El receptor filtrado se conserva en memoria para que no desaparezca de
  // la lista cuando una búsqueda posterior lo excluye de `receptores`.
  const receptorFiltroSeleccionadoRef = useRef<Receptor | null>(null)
  const receptorFiltroActual = receptores.find(r => r.id === filtroReceptor)
  if (receptorFiltroActual) receptorFiltroSeleccionadoRef.current = receptorFiltroActual
  const receptorFiltroSeleccionado = receptorFiltroActual
    ?? (receptorFiltroSeleccionadoRef.current?.id === filtroReceptor ? receptorFiltroSeleccionadoRef.current : undefined)
  const cuentasDelReceptorFiltro = receptorFiltroSeleccionado?.cuentas_bancarias ?? []
  // El receptor elegido debe seguir visible (y resaltado) en el desplegable
  // aunque quede fuera de los primeros 50 que devolvió la última búsqueda.
  const receptoresFiltroOpciones = receptorFiltroSeleccionado && !receptorFiltroActual
    ? [receptorFiltroSeleccionado, ...receptores]
    : receptores

  const idsReceptorNavegables = ['', ...receptoresFiltroOpciones.map(r => r.id)]
  // Resaltado y `aria-activedescendant` siguen SOLO la navegación explícita:
  // anunciar como activa una opción que Enter no confirma sería mentirle al
  // lector de pantalla. `null` = sin opción activa.
  const receptorIdActivo = receptorActivoId !== null && idsReceptorNavegables.includes(receptorActivoId)
    ? receptorActivoId
    : null

  const seleccionarReceptor = (receptorId: string) => {
    // Reafirmar el mismo receptor no debe limpiar el filtro de cuenta ni
    // resetear la paginación; el <select> nativo tampoco emitía onChange.
    if (receptorId !== filtroReceptor) handleFiltroReceptorChange(receptorId)
    // Cerrar es un cambio de estado, no soltar el foco: `Modal` y la página
    // no tienen focus trap, así que un blur dejaría el foco en <body>.
    setReceptorDropdownAbierto(false)
    setFiltroReceptorBusqueda('')
    setReceptorActivoId(null)
  }

  // El <select> que este combobox reemplaza era operable con teclado.
  const manejarTeclaReceptor = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!receptorDropdownAbierto) {
        setReceptorDropdownAbierto(true)
        return
      }
      const desde = receptorIdActivo
        ?? (idsReceptorNavegables.includes(filtroReceptor) ? filtroReceptor : idsReceptorNavegables[0])
      const actual = idsReceptorNavegables.indexOf(desde)
      const delta = e.key === 'ArrowDown' ? 1 : -1
      const siguiente = actual < 0
        ? 0
        : (actual + delta + idsReceptorNavegables.length) % idsReceptorNavegables.length
      setReceptorActivoId(idsReceptorNavegables[siguiente])
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (!receptorDropdownAbierto) return
      // Solo confirma navegación explícita, y solo si ese receptor sigue en
      // la lista: el refetch del debounce puede haberlo sacado.
      if (receptorActivoId === null || !idsReceptorNavegables.includes(receptorActivoId)) return
      seleccionarReceptor(receptorActivoId)
    } else if (e.key === 'Escape') {
      if (!receptorDropdownAbierto) return
      e.preventDefault()
      e.stopPropagation()
      setReceptorDropdownAbierto(false)
      setFiltroReceptorBusqueda('')
      setReceptorActivoId(null)
    }
  }

  const handleSolicitarRegistrar = () => {
    // Antes de registrar, mostrar confirmación con los montos
    setModalRegistrar(false)
    setModalConfirmarRegistrar(true)
  }

  const handleVolverRegistrar = () => {
    setModalConfirmarRegistrar(false)
    setModalRegistrar(true)
  }

  // Regla 14 (zero-balance-explicit-closure): tras un pago exitoso, re-lee el
  // crédito y si quedó con capital saldado e interés pendiente, ofrece el
  // diálogo de cierre explícito. Errores se ignoran: el pago ya se registró
  // correctamente; el listado de créditos sigue ofreciendo la acción.
  const verificarCierreInteresPendiente = async (creditoId: string) => {
    try {
      const res = await creditosApi.obtener(creditoId)
      if (res.data.puede_cerrar_con_interes_pendiente) {
        setCreditoCierre(res.data)
      }
    } catch {
      // silencioso — el pago ya se completó
    }
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
        cargarPagos(false)
        verificarCierreInteresPendiente(pagoSeleccionado.credito_id)
      }
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo registrar el pago')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
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
      cargarPagos(false)
      verificarCierreInteresPendiente(pagoSeleccionado.credito_id)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo confirmar el excedente')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
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
      cargarPagos(false)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo validar el pago')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
    }
  }

  const handleDesvalidar = async () => {
    if (!pagoADesvalidar || submitting) return
    setSubmitting(true)
    try {
      await pagosApi.desvalidar(pagoADesvalidar.id)
      toast.success('Check revertido')
      setPagoADesvalidar(null)
      cargarPagos(false)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo revertir el check')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
    } finally {
      setSubmitting(false)
    }
  }

  const handleModificarFecha = async () => {
    if (!pagoSeleccionado || !nuevaFecha) return
    setSubmitting(true)
    try {
      const vecesAplazadoPrevio = pagoSeleccionado.veces_aplazado ?? 0
      const res = await pagosApi.modificarFecha(pagoSeleccionado.id, nuevaFecha, esAplazamiento)
      const aplazamientoConfirmado = (res.data.veces_aplazado ?? 0) > vecesAplazadoPrevio
      if (esAplazamiento && !aplazamientoConfirmado) {
        toast.error('La fecha se actualizó, pero el aplazamiento no fue registrado por el servidor')
      } else {
        toast.success(esAplazamiento ? 'Aplazamiento registrado' : 'Fecha actualizada')
      }
      setModalFecha(false)
      cargarPagos(false)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo actualizar la fecha')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
    } finally { setSubmitting(false) }
  }

  const handleModificarCuentaBancaria = async () => {
    if (!pagoSeleccionado || !nuevaCuentaBancaria) return
    setSubmitting(true)
    try {
      await pagosApi.modificarCuentaBancaria(pagoSeleccionado.id, nuevaCuentaBancaria)
      toast.success('Cuenta bancaria actualizada')
      setModalCuentaBancaria(false)
      cargarPagos(false)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo actualizar la cuenta bancaria')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
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
      cargarPagos(false)
      verificarCierreInteresPendiente(npCreditoId)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo registrar el pago no programado')
      if (msg) toast.error(msg)
      if (e.response && !esErrorSesionExpirada(e)) cargarPagos(false)
    } finally { setSubmitting(false) }
  }

  const handleCerrarCreditoCierre = async () => {
    if (!creditoCierre) return
    setCerrandoCreditoCierre(true)
    try {
      await creditosApi.cerrar(creditoCierre.id, { cerrar_con_interes_pendiente: true })
      toast.success('Cierre del crédito confirmado')
      setCreditoCierre(null)
      cargarPagos(false)
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo confirmar el cierre')
      if (msg) toast.error(msg)
    } finally { setCerrandoCreditoCierre(false) }
  }

  const handleSeguirCobrandoCreditoCierre = () => {
    setCreditoCierre(null)
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
          {esSemanal ? 'Pagos Semanales' : esDiario ? 'Pagos Diarios' : esAplazados ? 'Pagos Aplazados' : 'Módulo de Pagos'}
        </h1>
        <div className="flex items-center gap-2">
          {esSemanal || esDiario || esAplazados ? (
            <button onClick={() => navigate('/pagos')} className="btn-ghost flex items-center gap-2">
              <ArrowLeft size={16} /> Volver a Pagos
            </button>
          ) : (
            <>
              <button onClick={() => navigate('/pagos/semanales')} className="btn-secondary flex items-center gap-2">
                <CalendarDays size={16} /> Pagos Semanales
              </button>
              <button onClick={() => navigate('/pagos/diarios')} className="btn-secondary flex items-center gap-2">
                <CalendarDays size={16} /> Pagos Diarios
              </button>
              <button onClick={() => navigate('/pagos/aplazados')} className="btn-secondary flex items-center gap-2">
                <CalendarDays size={16} /> Pagos Aplazados
              </button>
            </>
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
          {!esAplazados && (
            <>
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
                <label className="label">Momento {(esSemanal || esDiario) ? '(opcional)' : '*'}</label>
                <select className="input" value={momento} onChange={e => { setMomento(e.target.value); setPage(1) }}>
                  <option value="">{(esSemanal || esDiario) ? 'Todos los del mes' : '-- Seleccionar --'}</option>
                  {MOMENTOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
            </>
          )}
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
          {perms.canValidarPago && !esAplazados && (
            <>
              <div>
                <label className="label">Receptor</label>
                {/* Combobox: la lista de receptores que coinciden se despliega
                    mientras se escribe (el backend filtra `busqueda` por nombre
                    y cédula). */}
                <div className="relative">
                  <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                  <input
                    type="text"
                    role="combobox"
                    aria-expanded={receptorDropdownAbierto}
                    aria-haspopup="listbox"
                    aria-controls={idListboxReceptor}
                    aria-activedescendant={receptorDropdownAbierto && receptorIdActivo !== null ? `${idListboxReceptor}-${receptorIdActivo || 'todos'}` : undefined}
                    className={clsx('input pl-8 pr-8 text-sm', !receptorDropdownAbierto && !!filtroReceptor && 'placeholder:text-gray-900')}
                    // El input es siempre la caja de búsqueda; el receptor
                    // filtrado se muestra como placeholder. Así no existe el
                    // estado en que el input mostraba el nombre y lo tecleado
                    // se concatenaba a él antes de salir al backend.
                    placeholder={receptorDropdownAbierto
                      ? 'Nombre o cédula...'
                      : (receptorFiltroSeleccionado?.nombre ?? 'Todos')}
                    value={filtroReceptorBusqueda}
                    onMouseDown={() => setReceptorDropdownAbierto(true)}
                    onFocus={() => setReceptorDropdownAbierto(true)}
                    onBlur={() => {
                      setReceptorDropdownAbierto(false)
                      setFiltroReceptorBusqueda('')
                      setReceptorActivoId(null)
                    }}
                    onKeyDown={manejarTeclaReceptor}
                    onChange={e => {
                      setReceptorDropdownAbierto(true)
                      setFiltroReceptorBusqueda(e.target.value)
                      setReceptorActivoId(null)
                    }}
                  />
                  {filtroReceptor && !receptorDropdownAbierto && (
                    <button
                      type="button"
                      title="Quitar filtro"
                      onClick={() => handleFiltroReceptorChange('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      <X size={14} />
                    </button>
                  )}
                  {receptorDropdownAbierto && (
                    // preventDefault en el contenedor: arrastrar la barra de
                    // scroll no quita el foco del input ni cierra la lista.
                    <div
                      id={idListboxReceptor}
                      role="listbox"
                      className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-56 overflow-y-auto"
                      onMouseDown={e => e.preventDefault()}
                    >
                      <button
                        type="button"
                        id={`${idListboxReceptor}-todos`}
                        ref={el => { if (el && receptorIdActivo === '') el.scrollIntoView({ block: 'nearest' }) }}
                        role="option"
                        aria-selected={filtroReceptor === ''}
                        className={clsx(
                          'w-full text-left px-3 py-2 text-sm text-gray-500 hover:bg-primary-50 border-b border-gray-50',
                          receptorIdActivo === '' && 'bg-primary-100',
                        )}
                        onClick={() => seleccionarReceptor('')}
                      >
                        Todos
                      </button>
                      {receptoresFiltroOpciones.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-gray-400">Sin resultados</div>
                      ) : receptoresFiltroOpciones.map(r => (
                        <button
                          key={r.id}
                          type="button"
                          id={`${idListboxReceptor}-${r.id}`}
                          ref={el => { if (el && r.id === receptorIdActivo) el.scrollIntoView({ block: 'nearest' }) }}
                          role="option"
                          aria-selected={r.id === filtroReceptor}
                          className={clsx(
                            'w-full text-left px-3 py-2 text-sm hover:bg-primary-50 border-b border-gray-50 last:border-0',
                            r.id === filtroReceptor && 'font-medium',
                            r.id === receptorIdActivo && 'bg-primary-100',
                          )}
                          onClick={() => seleccionarReceptor(r.id)}
                        >
                          {r.nombre}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div>
                <label className="label">Cuenta</label>
                <select className="input" value={filtroCuentaBancaria}
                  disabled={!filtroReceptor}
                  onChange={e => { setFiltroCuentaBancaria(e.target.value); setPage(1) }}>
                  <option value="">Todas</option>
                  {cuentasDelReceptorFiltro.map(c => (
                    <option key={c.id} value={c.id}>{formatCuentaBancaria(c)}</option>
                  ))}
                </select>
              </div>
            </>
          )}
          {esAplazados && (
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm text-gray-600">
                <input
                  type="checkbox"
                  checked={incluirPagados}
                  onChange={e => { setIncluirPagados(e.target.checked); setPage(1) }}
                />
                Incluir pagados
              </label>
            </div>
          )}
        </div>
      </div>

      {/* Aviso filtros */}
      {!filtrosCompletos && (
        <div className="card text-center py-12 text-gray-400">
          <p className="text-4xl mb-3">🔍</p>
          <p className="font-medium">
            {esSemanal
              ? 'Selecciona año y mes para ver los pagos semanales.'
              : esDiario
                ? 'Selecciona año y mes para ver los pagos diarios.'
                : 'Selecciona año, mes y momento para ver los pagos.'}
          </p>
        </div>
      )}

      {/* Tabla */}
      {filtrosCompletos && (
        <div className="card p-0 overflow-hidden">
          {loading ? <LoadingPage /> : pagos.length === 0 ? (
            <EmptyState message={esAplazados ? 'No hay pagos aplazados' : 'No hay pagos para el período seleccionado'} />
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="table-header">Acciones</th>
                      <th className="table-header">Cuota</th>
                      <th className="table-header">Cliente</th>
                      <th className="table-header">Receptor / Cuenta</th>
                      <th className="table-header">Crédito</th>
                      <th className="table-header">Tipo</th>
                      <th className="table-header">Monto</th>
                      <th className="table-header">Capital</th>
                      <th className="table-header">Interés</th>
                      <th className="table-header">Cap. pagado</th>
                      <th className="table-header">Int. pagado</th>
                      <th
                        className="table-header cursor-pointer select-none"
                        onClick={handleSortToggle}
                      >
                        <span className="inline-flex items-center gap-1">
                          Fecha Máx.
                          {sortDir === 'asc' ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </span>
                      </th>
                      <th className="table-header">Momento</th>
                      <th className="table-header">Estado</th>
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
                          !p.es_proyectada && !p.vencido && !p.pagado && p.veces_aplazado > 0 && 'bg-violet-50',
                          !p.es_proyectada && p.vencido && 'bg-red-50',
                          p.es_ultimo_pago && 'border-l-4 border-l-accent',
                        )}
                        title={p.es_proyectada ? `Proyectada — ${p.razon_bloqueo ?? ''}` : undefined}
                      >
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
                                onClick={() => setPagoADesvalidar(p)}
                                disabled={submitting}
                                className="p-1.5 bg-orange-500 text-white rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
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
                                  setEsAplazamiento(false)
                                  setModalFecha(true)
                                }}
                                className="p-1.5 bg-yellow-500 text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <Calendar size={14} />
                              </button>
                            )}
                            {/* Modificar cuenta bancaria — un pago YA PAGADO abre el
                                reparto multi-destinatario (item 10, PR3); uno
                                pendiente sigue usando el modal de cuenta única,
                                porque PUT /pagos/{id}/repartos exige pagado=True. */}
                            {!p.es_proyectada && perms.canValidarPago && (
                              <button
                                title="Modificar cuenta"
                                onClick={() => {
                                  setPagoSeleccionado(p)
                                  if (p.pagado) {
                                    setModalReparto(true)
                                  } else {
                                    setNuevaCuentaBancaria(p.cuenta_bancaria_id ?? '')
                                    setModalCuentaBancaria(true)
                                  }
                                }}
                                className="p-1.5 bg-gray-500 text-white rounded-lg hover:opacity-90 transition-opacity"
                              >
                                <User size={14} />
                              </button>
                            )}
                          </div>
                        </td>
                        <td className="table-cell font-mono font-semibold">
                          {p.es_proyectada && <span className="mr-1">🔒</span>}
                          #{p.numero_cuota}
                        </td>
                        <td className={clsx('table-cell font-medium', p.es_proyectada ? 'text-gray-500' : 'text-gray-800')}>
                          {p.cliente_nombre || '—'}
                        </td>
                        <td className="table-cell text-xs text-gray-600">
                          {p.cuenta_bancaria
                            ? <div title={formatCuentaBancaria(p.cuenta_bancaria, p.cuenta_bancaria.receptor.nombre)}>
                                <div className="font-medium text-gray-800">{p.cuenta_bancaria.receptor.nombre}</div>
                                <div className="text-gray-500">
                                  {p.cuenta_bancaria.entidad_bancaria} · {p.cuenta_bancaria.numero_cuenta}
                                </div>
                              </div>
                            : '—'}
                        </td>
                        <td className="table-cell font-mono text-xs text-gray-500">{p.numero_credito_cliente || p.credito_id.slice(0, 8) + '...'}</td>
                        <td className="table-cell">
                          <span className="badge-info capitalize">{p.tipo_cuota.replace('_', ' ')}</span>
                        </td>
                        <td className="table-cell font-semibold text-primary-600">{formatCOP(p.monto_a_pagar)}</td>
                        <td className="table-cell text-gray-600">{formatCOP(p.capital_a_pagar)}</td>
                        <td className="table-cell text-gray-600">{formatCOP(p.interes_a_pagar)}</td>
                        <td className="table-cell text-green-700">{formatCOP(p.capital_pagado)}</td>
                        <td className="table-cell text-green-700">{formatCOP(p.interes_pagado)}</td>
                        <td className="table-cell">
                          <span className={clsx('text-xs', p.vencido && 'text-danger font-bold')}>
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
                          {!p.es_proyectada && p.en_mora && <span className="badge-danger ml-1">Vencido</span>}
                          {!p.es_proyectada && p.veces_aplazado > 0 && (
                            <span
                              className="ml-1 text-xs px-2 py-0.5 rounded-full font-medium bg-violet-100 text-violet-700"
                              title="Veces aplazado"
                            >
                              Aplazado ×{p.veces_aplazado}
                            </span>
                          )}
                          {p.es_ultimo_pago && <span className="badge-warning ml-1">Última</span>}
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
              {/* Regla 13 (zero-balance-credit-closure) aplica solo a cuota_fija:
                  en abono_capital la cuota de interés es la mitad estructural del
                  ciclo alternado, no evidencia de que el capital esté saldado.
                  tipo_credito null/undefined falla abierto (permite capital);
                  el backend sigue siendo la autoridad de validación. */}
              <input type="number" className="input" value={capitalPagado}
                disabled={pagoSeleccionado.tipo_credito === 'cuota_fija' && pagoSeleccionado.tipo_cuota === 'interes'}
                onChange={e => setCapitalPagado(e.target.value)} />
              {pagoSeleccionado.tipo_credito === 'cuota_fija' && pagoSeleccionado.tipo_cuota === 'interes' && (
                <p className="text-xs text-gray-500 mt-1">
                  Esta cuota es de solo interés: el capital ya está saldado.
                </p>
              )}
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
          <div>
            <label className="flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={esAplazamiento}
                onChange={e => setEsAplazamiento(e.target.checked)}
              />
              ¿Es un aplazamiento solicitado por el cliente?
            </label>
            <p className="text-xs text-gray-500 mt-1">
              Marque solo si el cliente pidió mover la fecha; se incrementará el contador.
            </p>
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalFecha(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleModificarFecha} disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Modificar cuenta bancaria */}
      <Modal isOpen={modalCuentaBancaria} onClose={() => setModalCuentaBancaria(false)} title="Modificar Cuenta">
        <div className="space-y-4">
          <div>
            <label className="label">Cuenta bancaria</label>
            <SelectCuentaBancaria
              receptores={receptoresCuenta}
              value={nuevaCuentaBancaria}
              onChange={setNuevaCuentaBancaria}
              onBusquedaChange={handleBusquedaReceptoresCuenta}
              cuentaActual={pagoSeleccionado?.cuenta_bancaria}
            />
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalCuentaBancaria(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleModificarCuentaBancaria} disabled={submitting || !nuevaCuentaBancaria} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </div>
      </Modal>

      {/* Modal: Reparto de pago pagado (item 10, PR3) */}
      <RepartoPagoModal
        isOpen={modalReparto}
        onClose={() => setModalReparto(false)}
        pago={pagoSeleccionado}
        receptores={receptoresCuenta}
        onBusquedaReceptores={handleBusquedaReceptoresCuenta}
        onSaved={() => { setModalReparto(false); cargarPagos(false) }}
      />

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

      {/* Modal: Revertir check. Reemplaza window.confirm() — bloqueado
          silenciosamente en iOS/Android cuando la app corre como PWA
          instalada (modo standalone), que es como suelen usarla los
          recaudadores en el celular. */}
      <Modal isOpen={pagoADesvalidar !== null} onClose={() => setPagoADesvalidar(null)} title="Revertir check" size="sm">
        <ConfirmDelete
          message={`¿Revertir el check de la cuota #${pagoADesvalidar?.numero_cuota} de ${pagoADesvalidar?.cliente_nombre}?`}
          onConfirm={handleDesvalidar}
          onCancel={() => setPagoADesvalidar(null)}
          loading={submitting}
          confirmLabel="Revertir"
          loadingLabel="Revirtiendo..."
        />
      </Modal>

      <ConfirmarCierreInteresPendiente
        isOpen={creditoCierre !== null}
        credito={creditoCierre}
        onCerrar={handleCerrarCreditoCierre}
        onSeguir={handleSeguirCobrandoCreditoCierre}
        loading={cerrandoCreditoCierre}
      />
    </div>
  )
}
