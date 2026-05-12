export { default as ConfirmarCreacion } from './ConfirmarCreacion'
export type { ItemConfirmacion } from './ConfirmarCreacion'

// Spinner de carga
export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const sizes = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-10 h-10' }
  return (
    <div className={`${sizes[size]} animate-spin rounded-full border-2 border-primary-200 border-t-primary-600`} />
  )
}

// Página de carga centrada
export function LoadingPage() {
  return (
    <div className="flex-1 flex items-center justify-center h-64">
      <div className="flex flex-col items-center gap-3">
        <Spinner size="lg" />
        <p className="text-gray-400 text-sm">Cargando...</p>
      </div>
    </div>
  )
}

// Estado vacío
export function EmptyState({ message }: { message: string }) {
  return (
    <div className="text-center py-16 text-gray-400">
      <div className="text-5xl mb-3">📭</div>
      <p className="text-sm">{message}</p>
    </div>
  )
}

// Badge de estado pago.
// Flujo: pendiente → validado (check del recaudador) → pagado (registro de montos).
export function PagoBadge({ pagado, validado }: { pagado: boolean; validado: boolean }) {
  if (pagado) return <span className="badge-success">Pagado</span>
  if (validado) return <span className="badge-info">Validado</span>
  return <span className="badge-warning">Pendiente</span>
}

// Badge mora
export function MoraBadge({ fechaMaxima }: { fechaMaxima: string }) {
  const hoy = new Date()
  const vence = new Date(fechaMaxima)
  if (vence < hoy) return <span className="badge-danger">Vencido</span>
  return null
}

// Paginación
interface PaginacionProps {
  page: number
  pages: number
  total: number
  onChange: (page: number) => void
}
export function Paginacion({ page, pages, total, onChange }: PaginacionProps) {
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 bg-white">
      <p className="text-xs text-gray-500">{total} registros en total</p>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="px-3 py-1 rounded-lg text-xs font-medium border border-gray-200 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Anterior
        </button>
        <span className="px-3 py-1 text-xs text-gray-600">
          {page} / {pages}
        </span>
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= pages}
          className="px-3 py-1 rounded-lg text-xs font-medium border border-gray-200 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Siguiente
        </button>
      </div>
    </div>
  )
}

// Confirmación de borrado
export function ConfirmDelete({
  message, onConfirm, onCancel, loading,
}: {
  message: string
  onConfirm: () => void
  onCancel: () => void
  loading?: boolean
}) {
  return (
    <div>
      <p className="text-sm text-gray-600 mb-6">{message}</p>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="btn-ghost">Cancelar</button>
        <button onClick={onConfirm} disabled={loading} className="btn-danger">
          {loading ? 'Eliminando...' : 'Eliminar'}
        </button>
      </div>
    </div>
  )
}

// Campo de formulario con error
export function FormField({
  label, error, children, required,
}: {
  label: string
  error?: string
  children: React.ReactNode
  required?: boolean
}) {
  return (
    <div>
      <label className="label">
        {label} {required && <span className="text-danger">*</span>}
      </label>
      {children}
      {error && <p className="text-xs text-danger mt-1">{error}</p>}
    </div>
  )
}

// Tarjeta de estadística para el dashboard
export function StatCard({
  label, value, sub, color = 'blue',
}: {
  label: string
  value: string | number
  sub?: string
  color?: 'blue' | 'yellow' | 'green' | 'red'
}) {
  const colors = {
    blue:   'bg-primary-600 text-white',
    yellow: 'bg-accent text-primary-600',
    green:  'bg-green-500 text-white',
    red:    'bg-danger text-white',
  }
  return (
    <div className={`${colors[color]} rounded-xl p-5 shadow-md`}>
      <p className="text-xs font-semibold uppercase tracking-wider opacity-80 mb-1">{label}</p>
      <p className="text-2xl font-black leading-tight">{value}</p>
      {sub && <p className="text-xs opacity-70 mt-1">{sub}</p>}
    </div>
  )
}
