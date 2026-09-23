import { useState } from 'react'
import { reportesApi } from '@/api'
import type { FiltroReporte } from '@/api'
import type { ReporteIngresos, ReporteCarteraVencida } from '@/types'
import { MESES, MOMENTOS, aniosDisponibles } from '@/utils/formatters'
import { LoadingPage } from '@/components/ui'
import IngresosReporteView from './IngresosReporteView'
import CarteraVencidaReporteView from './CarteraVencidaReporteView'
import toast from 'react-hot-toast'
import { BarChart3 } from 'lucide-react'

// reportes-cartera-vencida-y-rango-fechas (PR3, design D10): ReportesPage es
// el container — mantiene el estado de filtros y llama a la API. Renderiza
// IngresosReporteView o CarteraVencidaReporteView según `tipoReporte`. El
// modo por intervalo sigue el patrón de fechas de AuditoriaPage (`type=
// "date"`, estado string `YYYY-MM-DD`).

type TipoReporte = 'ingresos' | 'cartera_vencida'
type ModoFiltro = 'momento' | 'intervalo'

const TIPOS_REPORTE: { value: TipoReporte; label: string }[] = [
  { value: 'ingresos', label: 'Ingresos' },
  { value: 'cartera_vencida', label: 'Cartera Vencida' },
]

const MODOS_FILTRO: { value: ModoFiltro; label: string }[] = [
  { value: 'momento', label: 'Por momento' },
  { value: 'intervalo', label: 'Por intervalo' },
]

export default function ReportesPage() {
  const hoy = new Date()
  const [tipoReporte, setTipoReporte] = useState<TipoReporte>('ingresos')
  const [modoFiltro, setModoFiltro] = useState<ModoFiltro>('momento')

  const [anio, setAnio] = useState(hoy.getFullYear())
  const [mes, setMes] = useState(hoy.getMonth() + 1)
  const [momento, setMomento] = useState('')
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')

  const [reporteIngresos, setReporteIngresos] = useState<ReporteIngresos | null>(null)
  const [reporteCarteraVencida, setReporteCarteraVencida] = useState<ReporteCarteraVencida | null>(null)
  const [loading, setLoading] = useState(false)

  const cambiarTipoReporte = (tipo: TipoReporte) => {
    setTipoReporte(tipo)
    // design D10: se limpia el reporte visible al cambiar el tipo — los dos
    // shapes de respuesta nunca se mezclan.
    setReporteIngresos(null)
    setReporteCarteraVencida(null)
  }

  const generarReporte = async () => {
    let params: FiltroReporte
    if (modoFiltro === 'momento') {
      if (!momento) { toast.error('Selecciona el momento'); return }
      params = { anio, mes, momento }
    } else {
      if (!fechaDesde || !fechaHasta) { toast.error('Selecciona ambas fechas'); return }
      params = { fecha_desde: fechaDesde, fecha_hasta: fechaHasta }
    }

    setLoading(true)
    try {
      if (tipoReporte === 'ingresos') {
        const res = await reportesApi.ingresos(params)
        setReporteIngresos(res.data)
      } else {
        const res = await reportesApi.carteraVencida(params)
        setReporteCarteraVencida(res.data)
      }
    } catch (e: any) {
      toast.error(e.response?.data?.detail ?? 'Error al generar reporte')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <BarChart3 size={28} className="text-primary-600" />
        <h1 className="text-2xl font-black text-primary-600">Reportes Financieros</h1>
      </div>

      {/* Filtros */}
      <div className="card space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="label">Tipo de reporte *</label>
            <select
              className="input"
              value={tipoReporte}
              onChange={e => cambiarTipoReporte(e.target.value as TipoReporte)}
            >
              {TIPOS_REPORTE.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Filtrar *</label>
            <select
              className="input"
              value={modoFiltro}
              onChange={e => setModoFiltro(e.target.value as ModoFiltro)}
            >
              {MODOS_FILTRO.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </div>
        </div>

        {modoFiltro === 'momento' ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
            <div>
              <label className="label">Año *</label>
              <select className="input" value={anio} onChange={e => setAnio(+e.target.value)}>
                {aniosDisponibles().map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Mes *</label>
              <select className="input" value={mes} onChange={e => setMes(+e.target.value)}>
                {MESES.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Momento *</label>
              <select className="input" value={momento} onChange={e => setMomento(e.target.value)}>
                <option value="">-- Seleccionar --</option>
                {MOMENTOS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
            </div>
            <button onClick={generarReporte} disabled={loading} className="btn-primary py-2.5">
              {loading ? 'Generando...' : 'Generar Reporte'}
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 items-end">
            <div>
              <label className="label">Desde *</label>
              <input type="date" className="input" value={fechaDesde}
                onChange={e => setFechaDesde(e.target.value)} />
            </div>
            <div>
              <label className="label">Hasta *</label>
              <input type="date" className="input" value={fechaHasta}
                onChange={e => setFechaHasta(e.target.value)} />
            </div>
            <button onClick={generarReporte} disabled={loading} className="btn-primary py-2.5">
              {loading ? 'Generando...' : 'Generar Reporte'}
            </button>
          </div>
        )}
      </div>

      {loading && <LoadingPage />}

      {!loading && tipoReporte === 'ingresos' && reporteIngresos && (
        <IngresosReporteView reporte={reporteIngresos} />
      )}

      {!loading && tipoReporte === 'cartera_vencida' && reporteCarteraVencida && (
        <CarteraVencidaReporteView reporte={reporteCarteraVencida} />
      )}
    </div>
  )
}
