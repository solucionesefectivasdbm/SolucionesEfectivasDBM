import { useState, useEffect, useCallback } from 'react'
import { receptoresApi } from '@/api'
import { LoadingPage, EmptyState, Paginacion, ConfirmDelete, FormField, ConfirmarCreacion, type ItemConfirmacion } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import type { Receptor, CuentaBancaria } from '@/types'
import { Plus, Pencil, Trash2, Search, CreditCard } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'

export default function ReceptoresPage() {
  const [receptores, setReceptores] = useState<Receptor[]>([])
  const [total, setTotal] = useState(0); const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1); const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalForm, setModalForm] = useState(false)
  const [modalConfirmarCrear, setModalConfirmarCrear] = useState(false)
  const [datosPendientes, setDatosPendientes] = useState<any>(null)
  const [modalConfirmarCuenta, setModalConfirmarCuenta] = useState(false)
  const [datosCuentaPendientes, setDatosCuentaPendientes] = useState<any>(null)
  const [modalEliminar, setModalEliminar] = useState(false)
  const [modalCuentas, setModalCuentas] = useState(false)
  const [modalCuenta, setModalCuenta] = useState(false)
  const [editando, setEditando] = useState<Receptor | null>(null)
  const [seleccionado, setSeleccionado] = useState<Receptor | null>(null)
  const [editandoCuenta, setEditandoCuenta] = useState<CuentaBancaria | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<any>()
  const { register: regC, handleSubmit: handleC, reset: resetC } = useForm<any>()

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await receptoresApi.listar({ page, busqueda })
      setReceptores(res.data.items); setTotal(res.data.total); setPages(res.data.pages)
    } catch {} finally { setLoading(false) }
  }, [page, busqueda])

  useEffect(() => { cargar() }, [cargar])

  const onSubmit = async (data: any) => {
    if (editando) {
      setSubmitting(true)
      try {
        await receptoresApi.actualizar(editando.id, data)
        toast.success('Receptor actualizado')
        setModalForm(false); cargar()
      } catch (e: any) {
        const detail = e.response?.data?.detail
        const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
        toast.error(msg)
      }
      finally { setSubmitting(false) }
      return
    }
    setDatosPendientes(data)
    setModalForm(false)
    setModalConfirmarCrear(true)
  }

  const handleConfirmarCrear = async () => {
    if (!datosPendientes) return
    setSubmitting(true)
    try {
      await receptoresApi.crear(datosPendientes)
      toast.success('Receptor creado')
      setModalConfirmarCrear(false)
      setDatosPendientes(null)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const handleVolverFormulario = () => {
    setModalConfirmarCrear(false)
    setModalForm(true)
  }

  const itemsConfirmacion = (): ItemConfirmacion[] => {
    if (!datosPendientes) return []
    return [
      { label: 'Nombre', value: datosPendientes.nombre },
      { label: 'Cédula', value: datosPendientes.cedula },
      { label: 'Teléfono', value: datosPendientes.telefono },
    ]
  }

  const handleEliminar = async () => {
    if (!seleccionado) return
    setSubmitting(true)
    try {
      await receptoresApi.eliminar(seleccionado.id)
      toast.success('Receptor eliminado'); setModalEliminar(false); cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const onSubmitCuenta = async (data: any) => {
    if (!seleccionado) return
    if (editandoCuenta) {
      setSubmitting(true)
      try {
        await receptoresApi.actualizarCuenta(seleccionado.id, editandoCuenta.id, data)
        toast.success('Cuenta actualizada')
        setModalCuenta(false)
        const res = await receptoresApi.obtener(seleccionado.id)
        setSeleccionado(res.data)
        cargar()
      } catch (e: any) {
        const detail = e.response?.data?.detail
        const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
        toast.error(msg)
      }
      finally { setSubmitting(false) }
      return
    }
    // Crear cuenta — pedir confirmación
    setDatosCuentaPendientes(data)
    setModalCuenta(false)
    setModalConfirmarCuenta(true)
  }

  const handleConfirmarCrearCuenta = async () => {
    if (!seleccionado || !datosCuentaPendientes) return
    setSubmitting(true)
    try {
      await receptoresApi.agregarCuenta(seleccionado.id, datosCuentaPendientes)
      toast.success('Cuenta agregada')
      setModalConfirmarCuenta(false)
      setDatosCuentaPendientes(null)
      const res = await receptoresApi.obtener(seleccionado.id)
      setSeleccionado(res.data)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error'
      toast.error(msg)
    }
    finally { setSubmitting(false) }
  }

  const handleVolverCuenta = () => {
    setModalConfirmarCuenta(false)
    setModalCuenta(true)
  }

  const itemsCuenta = (): ItemConfirmacion[] => {
    if (!datosCuentaPendientes) return []
    return [
      { label: 'Entidad bancaria', value: datosCuentaPendientes.entidad_bancaria },
      { label: 'Tipo de cuenta', value: datosCuentaPendientes.tipo_cuenta },
      { label: 'Número de cuenta', value: datosCuentaPendientes.numero_cuenta },
    ]
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Receptores</h1>
        <button onClick={() => { setEditando(null); reset(); setModalForm(true) }} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Nuevo Receptor
        </button>
      </div>

      <div className="card">
        <div className="relative max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por nombre..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : receptores.length === 0 ? <EmptyState message="Sin receptores" /> : (
          <>
            <table className="w-full">
              <thead><tr>
                <th className="table-header">Nombre</th><th className="table-header">Cédula</th>
                <th className="table-header">Teléfono</th><th className="table-header">Cuentas</th>
                <th className="table-header">Acciones</th>
              </tr></thead>
              <tbody>
                {receptores.map((r, i) => (
                  <tr key={r.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                    <td className="table-cell font-medium">{r.nombre}</td>
                    <td className="table-cell font-mono text-xs">{r.cedula}</td>
                    <td className="table-cell">{r.telefono}</td>
                    <td className="table-cell">
                      <span className="badge-info">{r.cuentas_bancarias?.length ?? 0} cuenta(s)</span>
                    </td>
                    <td className="table-cell">
                      <div className="flex gap-1">
                        <button onClick={() => { setSeleccionado(r); setModalCuentas(true) }}
                          className="p-1.5 bg-primary-100 text-primary-700 rounded-lg hover:bg-primary-200" title="Ver cuentas">
                          <CreditCard size={13} />
                        </button>
                        <button onClick={() => { setEditando(r); reset(r); setModalForm(true) }}
                          className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                          <Pencil size={13} />
                        </button>
                        <button onClick={() => { setSeleccionado(r); setModalEliminar(true) }}
                          className="p-1.5 bg-danger text-white rounded-lg hover:opacity-90">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Paginacion page={page} pages={pages} total={total} onChange={setPage} />
          </>
        )}
      </div>

      <Modal isOpen={modalForm} onClose={() => setModalForm(false)} title={editando ? 'Editar Receptor' : 'Nuevo Receptor'}>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField label="Nombre" required><input {...register('nombre', { required: true })} className="input" /></FormField>
          <FormField label="Cédula" required><input {...register('cedula', { required: true, pattern: { value: /^\d{6,10}$/, message: 'Cédula: 6 a 10 dígitos numéricos' } })} className="input" inputMode="numeric" placeholder="Ej: 1234567890" /></FormField>
          <FormField label="Teléfono" required><input {...register('telefono', { required: true, pattern: { value: /^\d{7,10}$/, message: 'Teléfono: 7 a 10 dígitos numéricos' } })} className="input" inputMode="numeric" placeholder="Ej: 3001234567" /></FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalForm(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : editando ? 'Actualizar' : 'Crear'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalCuentas} onClose={() => setModalCuentas(false)}
        title={`Cuentas de ${seleccionado?.nombre}`} size="lg">
        <div className="space-y-3 mb-4">
          {seleccionado?.cuentas_bancarias?.length === 0
            ? <p className="text-center text-gray-400 text-sm py-4">Sin cuentas registradas</p>
            : seleccionado?.cuentas_bancarias?.map(c => (
              <div key={c.id} className="flex items-center justify-between bg-gray-50 rounded-lg p-3">
                <div>
                  <p className="text-sm font-semibold">{c.entidad_bancaria}</p>
                  <p className="text-xs text-gray-500">{c.tipo_cuenta} — {c.numero_cuenta}</p>
                </div>
                <button onClick={() => { setEditandoCuenta(c); resetC(c); setModalCuenta(true) }}
                  className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                  <Pencil size={13} />
                </button>
              </div>
            ))
          }
        </div>
        <button onClick={() => { setEditandoCuenta(null); resetC({}); setModalCuenta(true) }}
          className="btn-secondary w-full flex items-center justify-center gap-2">
          <Plus size={15} /> Agregar cuenta
        </button>
      </Modal>

      <Modal isOpen={modalCuenta} onClose={() => setModalCuenta(false)}
        title={editandoCuenta ? 'Editar Cuenta' : 'Nueva Cuenta'} size="sm">
        <form onSubmit={handleC(onSubmitCuenta)} className="space-y-4">
          <FormField label="Entidad bancaria" required>
            <input {...regC('entidad_bancaria', { required: true })} className="input" />
          </FormField>
          <FormField label="Tipo de cuenta" required>
            <select {...regC('tipo_cuenta', { required: true })} className="input">
              <option value="">-- Seleccionar --</option>
              <option value="Ahorros">Ahorros</option>
              <option value="Corriente">Corriente</option>
            </select>
          </FormField>
          <FormField label="Número de cuenta" required>
            <input {...regC('numero_cuenta', { required: true })} className="input" />
          </FormField>
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={() => setModalCuenta(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Guardar'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalConfirmarCrear} onClose={handleVolverFormulario} title="Confirmar nuevo receptor" size="md">
        <ConfirmarCreacion
          mensaje="Verifique los datos del nuevo receptor antes de crearlo."
          items={itemsConfirmacion()}
          onConfirmar={handleConfirmarCrear}
          onVolver={handleVolverFormulario}
          loading={submitting}
        />
      </Modal>

      <Modal isOpen={modalConfirmarCuenta} onClose={handleVolverCuenta} title="Confirmar nueva cuenta" size="md">
        <ConfirmarCreacion
          mensaje="Verifique los datos de la cuenta bancaria antes de agregarla."
          items={itemsCuenta()}
          onConfirmar={handleConfirmarCrearCuenta}
          onVolver={handleVolverCuenta}
          loading={submitting}
          textoConfirmar="Confirmar y agregar"
        />
      </Modal>

      <Modal isOpen={modalEliminar} onClose={() => setModalEliminar(false)} title="Eliminar Receptor" size="sm">
        <ConfirmDelete message={`¿Eliminar al receptor ${seleccionado?.nombre}?`}
          onConfirm={handleEliminar} onCancel={() => setModalEliminar(false)} loading={submitting} />
      </Modal>
    </div>
  )
}
