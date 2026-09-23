import { Fragment } from 'react'
import { formatCOP } from '@/utils/formatters'
import type { ReporteIngresos } from '@/types'

// reportes-cartera-vencida-y-rango-fechas (PR3, design D10): vista
// presentacional de /reportes/ingresos, extraída de ReportesPage para separar
// el container (estado/filtros) de la vista por tipo de reporte.

interface IngresosReporteViewProps {
  reporte: ReporteIngresos
}

export default function IngresosReporteView({ reporte }: IngresosReporteViewProps) {
  return (
    <div className="space-y-6">

      {/* Totales generales */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Recaudado */}
        <div className="card bg-primary-600 text-white border-0 space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider opacity-70">Recaudado</p>
          <p className="text-2xl font-black">{formatCOP(reporte.total_recaudado)}</p>
          <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-primary-400">
            <div className="flex justify-between">
              <span>Capital</span>
              <span>{formatCOP(reporte.total_capital_recaudado)}</span>
            </div>
            <div className="flex justify-between">
              <span>Intereses</span>
              <span>{formatCOP(reporte.total_intereses_recaudados)}</span>
            </div>
          </div>
        </div>

        {/* Pendiente */}
        <div className="card bg-yellow-500 text-white border-0 space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider opacity-70">Pendiente</p>
          <p className="text-2xl font-black">{formatCOP(reporte.total_pendiente)}</p>
          <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-yellow-400">
            <div className="flex justify-between">
              <span>Capital</span>
              <span>{formatCOP(reporte.total_capital_pendiente)}</span>
            </div>
            <div className="flex justify-between">
              <span>Intereses</span>
              <span>{formatCOP(reporte.total_intereses_pendientes)}</span>
            </div>
          </div>
        </div>

        {/* Total esperado */}
        <div className="card bg-primary-800 text-white border-0 space-y-2">
          <p className="text-xs font-bold uppercase tracking-wider opacity-70">Total Esperado</p>
          <p className="text-2xl font-black">{formatCOP(reporte.total_esperado)}</p>
          <div className="text-xs opacity-80 space-y-1 pt-1 border-t border-primary-600">
            <div className="flex justify-between">
              <span>Recaudado</span>
              <span>{formatCOP(reporte.total_recaudado)}</span>
            </div>
            <div className="flex justify-between">
              <span>Pendiente</span>
              <span>{formatCOP(reporte.total_pendiente)}</span>
            </div>
          </div>
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
                    <th className="table-header">Recaudado</th>
                    <th className="table-header">Capital Rec.</th>
                    <th className="table-header">Intereses Rec.</th>
                    <th className="table-header">Pendiente</th>
                    <th className="table-header">Capital Pend.</th>
                    <th className="table-header">Intereses Pend.</th>
                  </tr>
                </thead>
                <tbody>
                  {reporte.por_gestor.map((g, i) => (
                    <tr key={g.gestor_id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                      <td className="table-cell font-medium">{g.gestor_nombre}</td>
                      <td className="table-cell font-bold text-primary-600">{formatCOP(g.total_recaudado)}</td>
                      <td className="table-cell">{formatCOP(g.total_capital_recaudado)}</td>
                      <td className="table-cell">{formatCOP(g.total_intereses_recaudados)}</td>
                      <td className="table-cell font-bold text-yellow-600">{formatCOP(g.total_pendiente)}</td>
                      <td className="table-cell">{formatCOP(g.total_capital_pendiente)}</td>
                      <td className="table-cell">{formatCOP(g.total_intereses_pendientes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </div>

      {/* Por Receptor */}
      <div className="card">
        <h2 className="text-base font-bold text-primary-600 mb-4">Desglose por Receptor</h2>
        {reporte.por_receptor.length === 0
          ? <p className="text-gray-400 text-sm text-center py-4">Sin datos</p>
          : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="table-header">Receptor</th>
                    <th className="table-header">Recaudado</th>
                    <th className="table-header">Capital Rec.</th>
                    <th className="table-header">Intereses Rec.</th>
                    <th className="table-header">Pendiente</th>
                    <th className="table-header">Capital Pend.</th>
                    <th className="table-header">Intereses Pend.</th>
                  </tr>
                </thead>
                <tbody>
                  {reporte.por_receptor.map((r, i) => (
                    <Fragment key={r.receptor_id}>
                      <tr className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                        <td className="table-cell font-medium">{r.receptor_nombre}</td>
                        <td className="table-cell font-bold text-primary-600">{formatCOP(r.total_recaudado)}</td>
                        <td className="table-cell">{formatCOP(r.total_capital_recaudado)}</td>
                        <td className="table-cell">{formatCOP(r.total_intereses_recaudados)}</td>
                        <td className="table-cell font-bold text-yellow-600">{formatCOP(r.total_pendiente)}</td>
                        <td className="table-cell">{formatCOP(r.total_capital_pendiente)}</td>
                        <td className="table-cell">{formatCOP(r.total_intereses_pendientes)}</td>
                      </tr>
                      {r.por_cuenta.map((c) => (
                        <tr key={c.cuenta_bancaria_id} className="bg-gray-50/50">
                          <td className="table-cell text-xs text-gray-500 pl-6">↳ {c.etiqueta}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_recaudado)}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_capital_recaudado)}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_intereses_recaudados)}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_pendiente)}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_capital_pendiente)}</td>
                          <td className="table-cell text-xs text-gray-500">{formatCOP(c.total_intereses_pendientes)}</td>
                        </tr>
                      ))}
                    </Fragment>
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
