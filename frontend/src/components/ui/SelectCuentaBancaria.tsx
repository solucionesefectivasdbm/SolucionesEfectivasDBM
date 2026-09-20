import { useState, useEffect, useRef } from 'react'
import type { CuentaBancariaResumen, Receptor } from '@/types'
import { formatCuentaBancaria } from '@/utils/formatters'
import { Search } from 'lucide-react'

/**
 * Un solo <select> con un <optgroup> por receptor y sus cuentas bancarias
 * como opciones (design decision 11). Usado por el modal "Modificar cuenta"
 * de Pagos y por el formulario de Gestores.
 *
 * El backend limita `GET /receptores` a 50 resultados por página, por lo que
 * si se recibe `onBusquedaChange` se muestra un buscador que, tras un breve
 * debounce, delega en el caller la recarga de `receptores` con `busqueda`
 * (así cualquier receptor sigue siendo alcanzable más allá de los primeros
 * 50).
 *
 * El receptor dueño de la cuenta seleccionada nunca debe desaparecer del
 * <select>. Si el caller conoce la cuenta actual (p.ej. `pago.cuenta_bancaria`
 * o `gestor.cuenta_bancaria`), pásala en `cuentaActual`: ya trae su propio
 * `receptor` embebido, así que el grupo se sintetiza desde el primer render
 * aunque ese receptor esté fuera de los primeros 50 / de la búsqueda actual.
 * Como respaldo (cuando no se pasa `cuentaActual`) se sigue cacheando en
 * memoria el último receptor visto que sí incluía `value`.
 */
interface SelectCuentaBancariaProps {
  receptores: Receptor[]
  value: string
  onChange: (cuentaId: string) => void
  placeholder?: string
  className?: string
  disabled?: boolean
  id?: string
  onBusquedaChange?: (busqueda: string) => void
  cuentaActual?: CuentaBancariaResumen | null
}

export default function SelectCuentaBancaria({
  receptores,
  value,
  onChange,
  placeholder = '-- Seleccionar cuenta --',
  className = 'input',
  disabled,
  id,
  onBusquedaChange,
  cuentaActual,
}: SelectCuentaBancariaProps) {
  const [busqueda, setBusqueda] = useState('')

  // Latest callback kept in a ref so the debounce effect depends only on
  // `busqueda`: callers may pass a new inline handler on every render and
  // that must never re-trigger a fetch (it caused an infinite fetch loop).
  const onBusquedaChangeRef = useRef(onBusquedaChange)
  onBusquedaChangeRef.current = onBusquedaChange

  // Skip the initial `busqueda === ''` call on mount: callers already load
  // the unfiltered list themselves. Clearing the search after typing still
  // refetches because `busqueda` changes.
  const primeraEjecucionRef = useRef(true)

  useEffect(() => {
    if (primeraEjecucionRef.current) {
      primeraEjecucionRef.current = false
      return
    }
    const timer = setTimeout(() => onBusquedaChangeRef.current?.(busqueda), 300)
    return () => clearTimeout(timer)
  }, [busqueda])

  const receptorActual = receptores.find(r => r.cuentas_bancarias.some(c => c.id === value))

  // Respaldo cuando no se pasa `cuentaActual`: recuerda el último receptor
  // visto que sí incluía `value`.
  const receptorSeleccionadoRef = useRef<Receptor | null>(null)
  if (receptorActual) receptorSeleccionadoRef.current = receptorActual

  const receptorSintetizado: Receptor | null =
    !receptorActual && cuentaActual && cuentaActual.id === value
      ? {
          id: cuentaActual.receptor.id,
          nombre: cuentaActual.receptor.nombre,
          cedula: '',
          telefono: '',
          cuentas_bancarias: [cuentaActual],
        }
      : null

  const receptorAusente =
    receptorSintetizado ??
    (!receptorActual && !!value && receptorSeleccionadoRef.current?.cuentas_bancarias.some(c => c.id === value)
      ? receptorSeleccionadoRef.current
      : null)

  const listaReceptores = receptorAusente
    ? [receptorAusente, ...receptores.filter(r => r.id !== receptorAusente!.id)]
    : receptores

  return (
    <div className="space-y-2">
      {onBusquedaChange && (
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            className="input pl-9"
            placeholder="Buscar receptor..."
            value={busqueda}
            onChange={e => setBusqueda(e.target.value)}
          />
        </div>
      )}
      <select
        id={id}
        className={className}
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {listaReceptores
          .filter(receptor => receptor.cuentas_bancarias.length > 0)
          .map(receptor => (
            <optgroup key={receptor.id} label={receptor.nombre}>
              {receptor.cuentas_bancarias.map(cuenta => (
                <option key={cuenta.id} value={cuenta.id}>
                  {formatCuentaBancaria(cuenta)}
                </option>
              ))}
            </optgroup>
          ))}
      </select>
    </div>
  )
}
