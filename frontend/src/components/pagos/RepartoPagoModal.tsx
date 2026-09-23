import { useState, useEffect, useRef } from 'react'
import { pagosApi, clientesApi } from '@/api'
import { formatCOP } from '@/utils/formatters'
import { LoadingPage } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import SelectCuentaBancaria from '@/components/ui/SelectCuentaBancaria'
import { mensajeError } from '@/utils/apiErrors'
import type { Pago, Receptor, Cliente, TipoDestinatario, RepartoItem } from '@/types'
import { Plus, Trash2, X } from 'lucide-react'
import toast from 'react-hot-toast'
import clsx from 'clsx'

/**
 * Split de un Pago YA PAGADO entre N destinatarios (payment-multi-recipient,
 * item 10, PR3). Reemplaza el modal simple "Modificar cuenta" únicamente
 * para pagos pagados — un pago pendiente sigue usando ese modal, porque
 * `PUT /pagos/{id}/repartos` solo acepta pagos pagados (422 en cualquier
 * otro caso, ver spec.md "When split allowed").
 *
 * El backend reemplaza el set COMPLETO en cada guardado (no hay POST/PATCH/
 * DELETE por fila): create, edit y delete de una fila se logran editando el
 * array local y volviendo a enviar todo con `pagosApi.reemplazarRepartos`.
 * La suma debe cuadrar exactamente con `capital_pagado + interes_pagado`
 * (Decimal exacto en el backend, no la tolerancia de `_validar_split`) — acá
 * se compara en centavos para evitar el ruido de punto flotante de JS; el
 * backend sigue siendo la autoridad final de la validación.
 */

interface RepartoPagoModalProps {
  isOpen: boolean
  onClose: () => void
  pago: Pago | null
  receptores: Receptor[]
  onBusquedaReceptores?: (busqueda: string) => void
  onSaved: () => void
}

interface FilaReparto {
  key: string
  tipo_destinatario: TipoDestinatario
  cuenta_bancaria_id: string
  cliente_id: string
  clienteLabel: string
  monto: string
}

export default function RepartoPagoModal({
  isOpen, onClose, pago, receptores, onBusquedaReceptores, onSaved,
}: RepartoPagoModalProps) {
  const [filas, setFilas] = useState<FilaReparto[]>([])
  const [cargando, setCargando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const filaIdRef = useRef(0)

  const crearFilaVacia = (): FilaReparto => ({
    key: `nueva-${filaIdRef.current++}`,
    tipo_destinatario: 'cuenta_bancaria',
    cuenta_bancaria_id: '',
    cliente_id: '',
    clienteLabel: '',
    monto: '',
  })

  // Carga los repartos activos al abrir. Si un pago pagado no tuviera
  // ninguno todavía (no debería pasar — invariante I1 del backend), arranca
  // con una fila vacía en vez de dejar el modal sin nada que editar.
  useEffect(() => {
    if (!isOpen || !pago) { setFilas([]); return }
    let cancelado = false
    setCargando(true)
    pagosApi.obtenerRepartos(pago.id)
      .then(res => {
        if (cancelado) return
        setFilas(res.data.length > 0
          ? res.data.map(r => ({
              key: r.id,
              tipo_destinatario: r.tipo_destinatario,
              cuenta_bancaria_id: r.cuenta_bancaria_id ?? '',
              cliente_id: r.cliente_id ?? '',
              clienteLabel: r.tipo_destinatario === 'cliente' ? r.etiqueta : '',
              monto: String(r.monto),
            }))
          : [crearFilaVacia()])
      })
      .catch(e => {
        if (cancelado) return
        const msg = mensajeError(e, 'No se pudieron cargar los destinatarios')
        if (msg) toast.error(msg)
      })
      .finally(() => { if (!cancelado) setCargando(false) })
    return () => { cancelado = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, pago?.id])

  const actualizarFila = (idx: number, patch: Partial<FilaReparto>) => {
    setFilas(prev => prev.map((f, i) => i === idx ? { ...f, ...patch } : f))
  }

  const cambiarTipo = (idx: number, tipo: TipoDestinatario) => {
    actualizarFila(idx, { tipo_destinatario: tipo, cuenta_bancaria_id: '', cliente_id: '', clienteLabel: '' })
  }

  const quitarFila = (idx: number) => {
    setFilas(prev => prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev)
  }

  const agregarFila = () => setFilas(prev => [...prev, crearFilaVacia()])

  // El backend serializa Decimal como string en JSON ("50000.00"); el tipo
  // `Pago.capital_pagado`/`interes_pagado` dice `number` pero en runtime
  // llega string — sumarlos con `+` sin convertir hace concatenación
  // ("50000.00"+"0.00" -> "50000.000.00"), y esa cadena rota vuelve `NaN`
  // en cuanto se resta contra `asignado`, dejando "Guardar reparto"
  // deshabilitado para siempre. `Number(...)` fuerza la conversión antes.
  const totalObjetivo = pago ? Number(pago.capital_pagado) + Number(pago.interes_pagado) : 0
  const asignado = filas.reduce((acc, f) => acc + (parseFloat(f.monto) || 0), 0)
  // Redondeo a centavos: comparar floats de JS directamente contra 0 es
  // frágil (0.1 + 0.2 !== 0.3). Esto es solo el gate de habilitación del
  // botón — la igualdad exacta la valida el backend con Decimal.
  const restante = Math.round((totalObjetivo - asignado) * 100) / 100
  const balanceado = Math.abs(restante) < 0.005

  // Dos filas SIN destinatario elegido todavía (id === '') no cuentan como
  // "duplicadas" entre sí — de lo contrario, agregar una segunda fila en
  // blanco del mismo tipo (el flujo normal antes de completarla) dispara el
  // aviso de duplicado sin que el usuario haya elegido nada aún (Judgment
  // Day, ambos jueces, 2026-09-22).
  const idsDestinatarios = filas
    .map(f => `${f.tipo_destinatario}:${f.tipo_destinatario === 'cuenta_bancaria' ? f.cuenta_bancaria_id : f.cliente_id}`)
    .filter(id => !id.endsWith(':'))
  const sinDuplicados = new Set(idsDestinatarios).size === idsDestinatarios.length
  const filasCompletas = filas.every(f =>
    (f.tipo_destinatario === 'cuenta_bancaria' ? !!f.cuenta_bancaria_id : !!f.cliente_id)
    && (parseFloat(f.monto) || 0) > 0)
  const puedeGuardar = balanceado && sinDuplicados && filasCompletas && filas.length > 0 && !guardando && !cargando

  const handleGuardar = async () => {
    if (!pago || !puedeGuardar) return
    setGuardando(true)
    try {
      const items: RepartoItem[] = filas.map(f => ({
        tipo_destinatario: f.tipo_destinatario,
        cuenta_bancaria_id: f.tipo_destinatario === 'cuenta_bancaria' ? f.cuenta_bancaria_id : null,
        cliente_id: f.tipo_destinatario === 'cliente' ? f.cliente_id : null,
        monto: parseFloat(f.monto) || 0,
      }))
      await pagosApi.reemplazarRepartos(pago.id, items)
      toast.success('Reparto actualizado')
      onSaved()
    } catch (e: any) {
      const msg = mensajeError(e, 'No se pudo actualizar el reparto')
      if (msg) toast.error(msg)
    } finally {
      setGuardando(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Repartir Pago" size="lg">
      {!pago ? null : cargando ? <LoadingPage /> : (
        <div className="space-y-4">
          <div className="bg-primary-50 rounded-lg p-3 text-sm">
            <p className="font-semibold text-primary-700">
              Cuota #{pago.numero_cuota} — {pago.cliente_nombre || '—'}
            </p>
            <p className="text-gray-600">Total pagado: <strong>{formatCOP(totalObjetivo)}</strong></p>
          </div>

          <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
            {filas.map((fila, idx) => (
              <div key={fila.key} className="border border-gray-200 rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <select
                    className="input w-44"
                    value={fila.tipo_destinatario}
                    onChange={e => cambiarTipo(idx, e.target.value as TipoDestinatario)}
                  >
                    <option value="cuenta_bancaria">Cuenta bancaria</option>
                    <option value="cliente">Cliente</option>
                  </select>
                  <button
                    type="button"
                    title="Quitar destinatario"
                    onClick={() => quitarFila(idx)}
                    disabled={filas.length <= 1}
                    className="p-1.5 text-gray-400 hover:text-danger disabled:opacity-30 disabled:cursor-not-allowed"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>

                {fila.tipo_destinatario === 'cuenta_bancaria' ? (
                  <SelectCuentaBancaria
                    receptores={receptores}
                    value={fila.cuenta_bancaria_id}
                    onChange={id => actualizarFila(idx, { cuenta_bancaria_id: id })}
                    onBusquedaChange={onBusquedaReceptores}
                  />
                ) : (
                  <BuscadorCliente
                    value={fila.cliente_id}
                    label={fila.clienteLabel}
                    onSelect={(id, label) => actualizarFila(idx, { cliente_id: id, clienteLabel: label })}
                    onClear={() => actualizarFila(idx, { cliente_id: '', clienteLabel: '' })}
                  />
                )}

                <div>
                  <label className="label">Monto</label>
                  <input
                    type="number" className="input" min="0" step="0.01"
                    value={fila.monto}
                    onChange={e => actualizarFila(idx, { monto: e.target.value })}
                    placeholder="0"
                  />
                </div>
              </div>
            ))}
          </div>

          <button type="button" onClick={agregarFila} className="btn-secondary w-full flex items-center justify-center gap-2">
            <Plus size={14} /> Agregar destinatario
          </button>

          <div className={clsx(
            'rounded-lg p-3 text-sm flex items-center justify-between font-medium',
            balanceado ? 'bg-green-50 text-green-700' : restante > 0 ? 'bg-yellow-50 text-yellow-700' : 'bg-red-50 text-danger',
          )}>
            <span>Asignado: {formatCOP(asignado)}</span>
            <span>
              {balanceado ? 'Cuadrado' : restante > 0
                ? `Restante: ${formatCOP(restante)}`
                : `Excede por: ${formatCOP(Math.abs(restante))}`}
            </span>
          </div>
          {!sinDuplicados && (
            <p className="text-xs text-danger">Hay destinatarios duplicados — cada uno debe aparecer una sola vez.</p>
          )}

          <div className="flex gap-3 justify-end">
            <button onClick={onClose} className="btn-ghost">Cancelar</button>
            <button onClick={handleGuardar} disabled={!puedeGuardar} className="btn-primary">
              {guardando ? 'Guardando...' : 'Guardar reparto'}
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// ─── Buscador de cliente (destinatario tipo `cliente`) ─────────────────────
// Búsqueda simple por nombre/cédula vía `clientesApi.listar({ busqueda })` —
// nunca texto libre (spec.md "Free-text client recipient rejected"): solo
// `onSelect` con un `cliente_id` real deja la fila válida.

interface BuscadorClienteProps {
  value: string
  label: string
  onSelect: (clienteId: string, label: string) => void
  onClear: () => void
}

function BuscadorCliente({ value, label, onSelect, onClear }: BuscadorClienteProps) {
  const [busqueda, setBusqueda] = useState('')
  const [resultados, setResultados] = useState<Cliente[]>([])

  useEffect(() => {
    if (!busqueda.trim()) { setResultados([]); return }
    let cancelado = false
    const timer = setTimeout(() => {
      clientesApi.listar({ busqueda, page: 1 })
        .then(r => { if (!cancelado) setResultados(r.data.items) })
        .catch(() => { if (!cancelado) setResultados([]) })
    }, 300)
    return () => { cancelado = true; clearTimeout(timer) }
  }, [busqueda])

  if (value && label) {
    return (
      <div className="input flex items-center justify-between">
        <span className="truncate">{label}</span>
        <button type="button" title="Quitar cliente" onClick={onClear} className="text-gray-400 hover:text-gray-600 ml-2 flex-shrink-0">
          <X size={14} />
        </button>
      </div>
    )
  }

  return (
    <div className="relative">
      <input
        type="text"
        className="input"
        placeholder="Buscar cliente por nombre o cédula..."
        value={busqueda}
        onChange={e => setBusqueda(e.target.value)}
      />
      {busqueda.trim() && (
        <div className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {resultados.length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-400">Sin resultados</div>
          ) : resultados.map(c => (
            <button
              key={c.id}
              type="button"
              className="w-full text-left px-3 py-2 text-sm hover:bg-primary-50 border-b border-gray-50 last:border-0"
              onClick={() => { onSelect(c.id, `${c.nombre} ${c.apellidos}`); setBusqueda('') }}
            >
              <span className="font-medium">{c.nombre} {c.apellidos}</span>
              <span className="text-gray-400 ml-2">{c.cedula}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
