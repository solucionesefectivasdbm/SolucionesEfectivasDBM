import { useState, useEffect, useId, useRef } from 'react'
import type { CuentaBancariaResumen, Receptor } from '@/types'
import { formatCuentaBancaria } from '@/utils/formatters'
import { Search, X } from 'lucide-react'
import clsx from 'clsx'

/**
 * Combobox de cuentas bancarias agrupadas por receptor (design decision 11).
 * Usado por el modal "Modificar cuenta" de Pagos y por el formulario de
 * Gestores. Al escribir se despliega la lista de receptores/cuentas que
 * coinciden con el texto.
 *
 * El backend limita `GET /receptores` a 50 resultados por página, por lo que
 * si se recibe `onBusquedaChange` el texto escrito, tras un breve debounce,
 * se delega en el caller para recargar `receptores` con `busqueda` (así
 * cualquier receptor sigue siendo alcanzable más allá de los primeros 50).
 * Sin `onBusquedaChange` el filtrado es local sobre `receptores`.
 *
 * El receptor dueño de la cuenta seleccionada nunca debe desaparecer de la
 * lista. Si el caller conoce la cuenta actual (p.ej. `pago.cuenta_bancaria`
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
  const [abierto, setAbierto] = useState(false)
  // Opción resaltada por teclado. `null` = seguir a `value`.
  const [activoId, setActivoId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const idListbox = `${useId()}-cuentas`

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

  const cuentaSeleccionada = listaReceptores
    .flatMap(receptor => receptor.cuentas_bancarias.map(cuenta => ({ cuenta, receptor })))
    .find(par => par.cuenta.id === value)

  const etiquetaSeleccionada = cuentaSeleccionada
    ? formatCuentaBancaria(cuentaSeleccionada.cuenta, cuentaSeleccionada.receptor.nombre)
    : ''

  // Con `onBusquedaChange` el filtrado ya lo hizo el backend; sin él se filtra
  // en memoria por nombre de receptor o datos de la cuenta.
  const textoBuscador = onBusquedaChange
    ? 'Buscar por nombre o cédula...'
    : 'Buscar receptor o cuenta...'

  const termino = busqueda.trim().toLowerCase()
  const grupos = listaReceptores
    .filter(receptor => receptor.cuentas_bancarias.length > 0)
    .map(receptor => {
      if (onBusquedaChange || !termino) return receptor
      if (receptor.nombre.toLowerCase().includes(termino)) return receptor
      const cuentas = receptor.cuentas_bancarias.filter(cuenta =>
        formatCuentaBancaria(cuenta).toLowerCase().includes(termino),
      )
      return cuentas.length > 0 ? { ...receptor, cuentas_bancarias: cuentas } : null
    })
    .filter((receptor): receptor is Receptor => receptor !== null)

  // Orden navegable con teclado: la opción de limpiar (`''`) y luego cada
  // cuenta en el orden en que se pintan.
  const idsNavegables = ['', ...grupos.flatMap(receptor => receptor.cuentas_bancarias.map(c => c.id))]
  // Resaltado por defecto = la selección actual. NO se adivina "la primera
  // coincidencia": con `onBusquedaChange` la lista sigue stale durante el
  // debounce y el receptor de la cuenta elegida va fijado al principio, así
  // que un índice fijo apuntaría a una cuenta que el usuario no buscó.
  const idActivo = activoId !== null && idsNavegables.includes(activoId)
    ? activoId
    : (idsNavegables.includes(value) ? value : idsNavegables[0])

  const seleccionar = (cuentaId: string) => {
    onChange(cuentaId)
    setBusqueda('')
    setActivoId(null)
    // Blur explícito: `onBlur` es lo único que cierra la lista (el
    // contenedor hace preventDefault para sobrevivir al arrastre del scroll),
    // y al soltar el foco el input vuelve a mostrar la etiqueta elegida.
    inputRef.current?.blur()
  }

  const mover = (delta: number) => {
    const actual = idsNavegables.indexOf(idActivo)
    const siguiente = actual < 0
      ? 0
      : (actual + delta + idsNavegables.length) % idsNavegables.length
    setActivoId(idsNavegables[siguiente])
  }

  // El <select> nativo que este combobox reemplaza era operable con teclado,
  // así que flechas/Enter/Escape son obligatorios, no un extra.
  const manejarTecla = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!abierto) {
        setAbierto(true)
        return
      }
      mover(e.key === 'ArrowDown' ? 1 : -1)
    } else if (e.key === 'Enter') {
      if (!abierto) return
      e.preventDefault()
      // Solo confirma navegación explícita, y solo si esa opción sigue en
      // la lista: el refetch del debounce puede haberla sacado, y confirmar
      // un id que ya no se ve elegiría una cuenta que el usuario no aprobó.
      if (activoId === null || !idsNavegables.includes(activoId)) return
      seleccionar(activoId)
    } else if (e.key === 'Escape') {
      if (!abierto) return
      e.preventDefault()
      // Sin stopPropagation el keydown llega al listener de Modal y cierra
      // el formulario entero, perdiendo lo que el usuario venía cargando.
      e.stopPropagation()
      setBusqueda('')
      setActivoId(null)
      inputRef.current?.blur()
    }
  }

  return (
    <div className="relative">
      <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
      <input
        id={id}
        ref={inputRef}
        type="text"
        role="combobox"
        aria-expanded={abierto}
        aria-haspopup="listbox"
        aria-controls={idListbox}
        aria-activedescendant={abierto ? `${idListbox}-${idActivo || 'vacio'}` : undefined}
        className={clsx(className, 'pl-9 pr-8')}
        disabled={disabled}
        placeholder={abierto ? textoBuscador : placeholder}
        value={abierto ? busqueda : etiquetaSeleccionada}
        // Defensa por si el input ya tuviera el foco (p. ej. tras Tab): un
        // click no dispara `onFocus` y la lista no se abriría.
        onMouseDown={() => setAbierto(true)}
        onFocus={() => setAbierto(true)}
        onBlur={() => { setAbierto(false); setBusqueda(''); setActivoId(null) }}
        onKeyDown={manejarTecla}
        // Defensa: teclear siempre deja la lista abierta.
        onChange={e => { setAbierto(true); setBusqueda(e.target.value); setActivoId(null) }}
      />
      {!!value && !abierto && !disabled && (
        <button
          type="button"
          title="Quitar cuenta"
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
        >
          <X size={15} />
        </button>
      )}
      {abierto && (
        // preventDefault en el contenedor (no solo en cada opción): así
        // arrastrar la barra de scroll o presionar una cabecera de grupo no
        // quita el foco del input ni cierra la lista.
        <div
          id={idListbox}
          role="listbox"
          className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-56 overflow-y-auto"
          onMouseDown={e => e.preventDefault()}
        >
          <button
            type="button"
            id={`${idListbox}-vacio`}
            ref={el => { if (el && idActivo === '') el.scrollIntoView({ block: 'nearest' }) }}
            role="option"
            aria-selected={value === ''}
            className={clsx(
              'w-full text-left px-3 py-2 text-sm text-gray-500 hover:bg-primary-50 border-b border-gray-50',
              idActivo === '' && 'bg-primary-100',
            )}
            onClick={() => seleccionar('')}
          >
            {placeholder}
          </button>
          {grupos.length === 0 ? (
            <div className="px-3 py-2 text-sm text-gray-400">Sin resultados</div>
          ) : grupos.map(receptor => (
            <div key={receptor.id}>
              <div className="px-3 py-1 text-xs font-semibold text-gray-500 bg-gray-50">
                {receptor.nombre}
              </div>
              {receptor.cuentas_bancarias.map(cuenta => (
                <button
                  key={cuenta.id}
                  type="button"
                  id={`${idListbox}-${cuenta.id}`}
                  ref={el => { if (el && cuenta.id === idActivo) el.scrollIntoView({ block: 'nearest' }) }}
                  role="option"
                  aria-selected={cuenta.id === value}
                  className={clsx(
                    'w-full text-left px-3 py-2 text-sm hover:bg-primary-50 border-b border-gray-50 last:border-0',
                    cuenta.id === value && 'font-medium',
                    cuenta.id === idActivo && 'bg-primary-100',
                  )}
                  onClick={() => seleccionar(cuenta.id)}
                >
                  {formatCuentaBancaria(cuenta)}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
