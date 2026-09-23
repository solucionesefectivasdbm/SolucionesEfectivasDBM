import { formatCOP } from '@/utils/formatters'
import type { ReporteCarteraVencida } from '@/types'

// reportes-cartera-vencida-y-rango-fechas (PR3, design D10): vista
// presentacional de /reportes/cartera-vencida. Sin desglose por receptor
// (spec: "No receptor breakdown in the response") — son cuotas no recibidas.

interface CarteraVencidaReporteViewProps {
  reporte: ReporteCarteraVencida
}

export default function CarteraVencidaReporteView({ reporte }: CarteraVencidaReporteViewProps) {
  return (
    <div className="space-y-6">

      {/* Totales generales */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="card bg-yellow-500 text-white border-0 space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider opacity-70">Total Vencido</p>
          <p className="text-2xl font-black">{formatCOP(reporte.total_vencido)}</p>
          <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-yellow-400">
            <div className="flex justify-between">
              <span>Capital</span>
              <span>{formatCOP(reporte.total_capital_vencido)}</span>
            </div>
            <div className="flex justify-between">
              <span>Intereses</span>
              <span>{formatCOP(reporte.total_intereses_vencidos)}</span>
            </div>
          </div>
        </div>

        <div className="card space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider text-gray-400">Cuotas Vencidas</p>
          <p className="text-2xl font-black text-primary-600">{reporte.cantidad_cuotas}</p>
        </div>
      </div>

      {/* Por Gestor */}
      <div className="card">
        <h2 className="text-base font-bold text-primary-600 mb-4">Desglose por Gestor</h2>
        {reporte.por_gestor.length === 0
          ? <p className="text-gray-400 text-sm text-center py-4">Sin datos</p>
          : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="table-header">Gestor</th>
                    <th className="table-header">Cuotas</th>
                    <th className="table-header">Total Vencido</th>
                    <th className="table-header">Capital Vencido</th>
                    <th className="table-header">Intereses Vencidos</th>
                  </tr>
                </thead>
                <tbody>
                  {reporte.por_gestor.map((g, i) => (
                    <tr key={g.gestor_id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                      <td className="table-cell font-medium">{g.gestor_nombre}</td>
                      <td className="table-cell">{g.cantidad_cuotas}</td>
                      <td className="table-cell font-bold text-yellow-600">{formatCOP(g.total_vencido)}</td>
                      <td className="table-cell">{formatCOP(g.total_capital_vencido)}</td>
                      <td className="table-cell">{formatCOP(g.total_intereses_vencidos)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </div>

    </div>
  )
}
