/**
 * ConfirmarCreacion — paso de validación antes de crear/registrar.
 *
 * Muestra una lista de pares (etiqueta, valor) con la información
 * que el usuario está por enviar. Botones:
 *   - "Volver al formulario": cierra esta vista para que el usuario corrija.
 *   - "Confirmar": ejecuta la acción real.
 */
import type { ReactNode } from 'react'

export interface ItemConfirmacion {
  label: string
  value: ReactNode
}

interface Props {
  /** Mensaje principal — ej: "Confirma la información del nuevo cliente" */
  mensaje?: string
  items: ItemConfirmacion[]
  onConfirmar: () => void
  onVolver: () => void
  loading?: boolean
  textoConfirmar?: string
  textoVolver?: string
}

export default function ConfirmarCreacion({
  mensaje,
  items,
  onConfirmar,
  onVolver,
  loading,
  textoConfirmar = 'Confirmar y crear',
  textoVolver = 'Volver al formulario',
}: Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        {mensaje ?? 'Verifique que la información esté correcta antes de continuar.'}
      </p>
      <div className="bg-gray-50 border border-gray-200 rounded-lg divide-y divide-gray-100 overflow-hidden">
        {items.map((it, i) => (
          <div key={i} className="flex items-start justify-between gap-4 px-3 py-2 text-sm">
            <span className="text-gray-500 shrink-0">{it.label}</span>
            <span className="font-medium text-gray-800 text-right break-words">
              {it.value === '' || it.value === null || it.value === undefined ? '—' : it.value}
            </span>
          </div>
        ))}
      </div>
      <div className="flex gap-3 justify-end pt-2">
        <button type="button" onClick={onVolver} disabled={loading} className="btn-ghost">
          {textoVolver}
        </button>
        <button type="button" onClick={onConfirmar} disabled={loading} className="btn-primary">
          {loading ? 'Procesando...' : textoConfirmar}
        </button>
      </div>
    </div>
  )
}
