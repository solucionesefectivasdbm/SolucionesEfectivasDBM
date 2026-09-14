/**
 * ConfirmarCierreInteresPendiente — regla 14 (zero-balance-explicit-closure).
 *
 * Diálogo compartido (listado de créditos + pagos) para el crédito
 * `cuota_fija` con capital saldado pero interés pendiente: el operador
 * decide explícitamente si cierra el crédito (condonando el interés
 * restante, que nunca fue deuda ni condonación — es interés simple no
 * devengado) o sigue cobrándolo (comportamiento por defecto, regla 10).
 */
import Modal from './Modal'
import { formatCOP } from '../../utils/formatters'
import type { Credito } from '../../types'

interface Props {
  isOpen: boolean
  credito: Credito | null
  onCerrar: () => void
  onSeguir: () => void
  loading?: boolean
}

export default function ConfirmarCierreInteresPendiente({
  isOpen, credito, onCerrar, onSeguir, loading,
}: Props) {
  return (
    <Modal isOpen={isOpen} title="Cerrar crédito con interés pendiente" onClose={onSeguir}>
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Crédito con saldo de capital en 0 pero interés pendiente de{' '}
          {credito ? formatCOP(credito.saldo_intereses) : '—'}. ¿Desea cerrarlo o seguir
          cobrando el interés pendiente?
        </p>
        <div className="flex gap-3 justify-end pt-2">
          <button type="button" onClick={onSeguir} disabled={loading} className="btn-ghost">
            Seguir cobrando
          </button>
          <button type="button" onClick={onCerrar} disabled={loading} className="btn-primary">
            {loading ? 'Cerrando...' : 'Cerrar crédito'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
