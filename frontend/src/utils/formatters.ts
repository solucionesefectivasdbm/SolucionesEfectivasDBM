/**
 * Formatea un número como moneda COP.
 * Formato colombiano: 1.250.000,50
 * DECISIÓN: Una sola función para todos los montos del sistema.
 * Nunca formatear montos inline en los componentes.
 */
export const formatCOP = (value: number | string): string => {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '$ 0,00'
  return new Intl.NumberFormat('es-CO', {
    style: 'currency',
    currency: 'COP',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

export const formatNumero = (value: number | string): string => {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return '0,00'
  return new Intl.NumberFormat('es-CO', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(num)
}

export const formatFecha = (fecha: string | null): string => {
  if (!fecha) return '—'
  const [year, month, day] = fecha.split('-')
  return `${day}/${month}/${year}`
}

export const formatPorcentaje = (valor: number): string => {
  return `${(valor * 100).toFixed(2)}%`
}

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

export const MOMENTOS = [
  { value: 'm1', label: 'M1 (25-29)' },
  { value: 'm2', label: 'M2 (30-4)' },
  { value: 'm3', label: 'M3 (5-13)' },
  { value: 'm4', label: 'M4 (14-18)' },
  { value: 'm5', label: 'M5 (19-24)' },
]

export const aniosDisponibles = (): number[] => {
  const current = new Date().getFullYear()
  return [current - 1, current, current + 1]
}
