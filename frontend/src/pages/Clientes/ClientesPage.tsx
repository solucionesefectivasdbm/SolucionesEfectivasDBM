import { useState, useEffect, useCallback } from 'react'
import { clientesApi, gestoresApi, creditosApi } from '@/api'
import { LoadingPage, EmptyState, Paginacion, ConfirmDelete, FormField } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import { usePermissions } from '@/store/authStore'
import type { Cliente, Gestor, Credito, Pago } from '@/types'
import { Plus, Pencil, Trash2, Search, CheckCircle, XCircle, Eye } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { formatCOP, formatFecha, formatPorcentaje } from '@/utils/formatters'
import toast from 'react-hot-toast'

interface ClienteForm {
  nombre: string; apellidos: string; cedula: string; telefono: string
  direccion: string; correo_electronico: string; afiliacion_militar: boolean
  gestor_id: string; al_dia: boolean
}

export default function ClientesPage() {
  const perms = usePermissions()
  const [clientes, setClientes] = useState<Cliente[]>([])
  const [gestores, setGestores] = useState<Gestor[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [busqueda, setBusqueda] = useState('')
  const [filtroGestor, setFiltroGestor] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalForm, setModalForm] = useState(false)
  const [modalEliminar, setModalEliminar] = useState(false)
  const [editando, setEditando] = useState<Cliente | null>(null)
  const [eliminando, setEliminando] = useState<Cliente | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [modalHistorial, setModalHistorial] = useState(false)
  const [clienteHistorial, setClienteHistorial] = useState<Cliente | null>(null)
  const [creditosCliente, setCreditosCliente] = useState<Credito[]>([])
  const [pagosCredito, setPagosCredito] = useState<Pago[]>([])
  const [creditoSeleccionado, setCreditoSeleccionado] = useState<Credito | null>(null)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<ClienteForm>()

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await clientesApi.listar({ page, busqueda, gestor_id: filtroGestor || undefined })
      setClientes(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch { toast.error('Error al cargar clientes') }
    finally { setLoading(false) }
  }, [page, busqueda, filtroGestor])

  useEffect(() => { cargar() }, [cargar])

  useEffect(() => {
    gestoresApi.listar({ page: 1 }).then(r => setGestores(r.data.items)).catch(() => {})
  }, [])

  const abrirCrear = () => {
    setEditando(null)
    reset({ afiliacion_militar: false, al_dia: true })
    setModalForm(true)
  }

  const abrirEditar = (c: Cliente) => {
    setEditando(c)
    reset({ ...c, correo_electronico: c.correo_electronico ?? '', gestor_id: c.gestor_id })
    setModalForm(true)
  }

  const onSubmit = async (data: ClienteForm) => {
    setSubmitting(true)
    try {
      if (editando) {
        await clientesApi.actualizar(editando.id, data)
        toast.success('Cliente actualizado')
      } else {
        await clientesApi.crear(data)
        toast.success('Cliente creado')
      }
      setModalForm(false)
      cargar()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      toast.error(Array.isArray(detail) ? detail.map((d: any) => d.msg).join(', ') : detail || 'Error')
    } finally { setSubmitting(false) }
  }

  const [soloActivosHistorial, setSoloActivosHistorial] = useState(true)

  const abrirHistorial = async (c: Cliente, soloActivos = true) => {
    setClienteHistorial(c)
    setCreditoSeleccionado(null)
    setPagosCredito([])
    setSoloActivosHistorial(soloActivos)
    try {
      const res = await creditosApi.listar({ cliente_id: c.id, solo_activos: soloActivos, page: 1 })
      setCreditosCliente(res.data.items)
      setModalHistorial(true)
    } catch { toast.error('Error al cargar historial') }
  }

  const verPagosCredito = async (credito: Credito) => {
    setCreditoSeleccionado(credito)
    try {
      const res = await creditosApi.historialCuotas(credito.id)
      setPagosCredito(res.data)
    } catch { toast.error('Error al cargar cuotas') }
  }

  const handleEliminar = async () => {
    if (!eliminando) return
    setSubmitting(true)
    try {
      await clientesApi.eliminar(eliminando.id)
      toast.success('Cliente eliminado')
      setModalEliminar(false)
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error')
    } finally { setSubmitting(false) }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Clientes</h1>
        {perms.canCreate && (
          <button onClick={abrirCrear} className="btn-primary flex items-center gap-2">
            <Plus size={16} /> Nuevo Cliente
          </button>
        )}
      </div>

      <div className="card flex items-center gap-4 flex-wrap">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por nombre..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
        <select className="input max-w-[220px]" value={filtroGestor}
          onChange={e => { setFiltroGestor(e.target.value); setPage(1) }}>
          <option value="">Todos los gestores</option>
          {gestores.map(g => <option key={g.id} value={g.id}>{g.nombre} {g.apellidos}</option>)}
        </select>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : clientes.length === 0 ? <EmptyState message="No hay clientes registrados" /> : (
          <>
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-header">Nombre</th>
                  <th className="table-header">Cédula</th>
                  <th className="table-header">Teléfono</th>
                  <th className="table-header">Al día</th>
                  <th className="table-header">Militar</th>
                  <th className="table-header">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {clientes.map((c, i) => (
                  <tr key={c.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                    <td className="table-cell font-medium">{c.nombre} {c.apellidos}</td>
                    <td className="table-cell font-mono text-xs">{c.cedula}</td>
                    <td className="table-cell">{c.telefono}</td>
                    <td className="table-cell">
                      {c.al_dia
                        ? <CheckCircle size={16} className="text-success" />
                        : <XCircle size={16} className="text-danger" />}
                    </td>
                    <td className="table-cell">
                      {c.afiliacion_militar ? <span className="badge-info">Sí</span> : '—'}
                    </td>
                    <td className="table-cell">
                      <div className="flex gap-1">
                        <button onClick={() => abrirHistorial(c)}
                          className="p-1.5 bg-primary-100 text-primary-700 rounded-lg hover:bg-primary-200" title="Ver historial">
                          <Eye size={13} />
                        </button>
                        {perms.canEdit && (
                          <button onClick={() => abrirEditar(c)}
                            className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                            <Pencil size={13} />
                          </button>
                        )}
                        {perms.canDelete && (
                          <button onClick={() => { setEliminando(c); setModalEliminar(true) }}
                            className="p-1.5 bg-danger text-white rounded-lg hover:opacity-90">
                            <Trash2 size={13} />
                          </button>
                        )}
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

      {/* Modal Formulario */}
      <Modal isOpen={modalForm} onClose={() => setModalForm(false)}
        title={editando ? 'Editar Cliente' : 'Nuevo Cliente'} size="lg">
        <form onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-2 gap-4">
          <FormField label="Nombre" required error={errors.nombre?.message}>
            <input {...register('nombre', { required: 'Requerido' })} className={`input ${errors.nombre ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Apellidos" required error={errors.apellidos?.message}>
            <input {...register('apellidos', { required: 'Requerido' })} className={`input ${errors.apellidos ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Cédula" required error={errors.cedula?.message}>
            <input {...register('cedula', {
              required: 'Requerido',
              pattern: { value: /^\d{6,10}$/, message: '6-10 dígitos' }
            })} className={`input ${errors.cedula ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Teléfono" required error={errors.telefono?.message}>
            <input {...register('telefono', {
              required: 'Requerido',
              pattern: { value: /^\d{7,10}$/, message: '7-10 dígitos' }
            })} className={`input ${errors.telefono ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Dirección" required error={errors.direccion?.message}>
            <input {...register('direccion', { required: 'Requerido' })} className="input" />
          </FormField>
          <FormField label="Correo electrónico">
            <input {...register('correo_electronico')} type="email" className="input" />
          </FormField>
          <FormField label="Gestor" required error={errors.gestor_id?.message}>
            <select {...register('gestor_id', { required: 'Requerido' })} className="input">
              <option value="">-- Seleccionar --</option>
              {gestores.map(g => <option key={g.id} value={g.id}>{g.nombre} {g.apellidos}</option>)}
            </select>
          </FormField>
          <div className="flex items-center gap-4 col-span-2">
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" {...register('afiliacion_militar')} className="w-4 h-4" />
              Afiliación militar
            </label>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" {...register('al_dia')} className="w-4 h-4" />
              Al día
            </label>
          </div>
          <div className="col-span-2 flex gap-3 justify-end pt-2">
            <button type="button" onClick={() => setModalForm(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : editando ? 'Actualizar' : 'Crear'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Modal Eliminar */}
      <Modal isOpen={modalEliminar} onClose={() => setModalEliminar(false)} title="Eliminar Cliente" size="sm">
        <ConfirmDelete
          message={`¿Eliminar al cliente ${eliminando?.nombre} ${eliminando?.apellidos}? Esta acción no se puede deshacer si el cliente no tiene créditos activos.`}
          onConfirm={handleEliminar}
          onCancel={() => setModalEliminar(false)}
          loading={submitting}
        />
      </Modal>

      {/* Modal Cartera del cliente */}
      <Modal isOpen={modalHistorial} onClose={() => { setModalHistorial(false); setCreditoSeleccionado(null) }}
        title={`Cartera — ${clienteHistorial?.nombre} ${clienteHistorial?.apellidos}`} size="xl">
        <div className="space-y-4">
          {/* Resumen de cartera */}
          <div className="bg-primary-50 border border-primary-200 rounded-lg p-4 flex items-center justify-between">
            <div>
              <p className="text-sm text-primary-700 font-medium">Saldo total de cartera</p>
              <p className="text-xs text-gray-500">{creditosCliente.filter(c => c.activo).length} crédito(s) activo(s)</p>
            </div>
            <p className="text-2xl font-black text-primary-700">
              {formatCOP(creditosCliente.filter(c => c.activo).reduce((sum, c) => sum + c.saldo_capital, 0))}
            </p>
          </div>

          {/* Filtro activos/todos */}
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-primary-600">Créditos</h3>
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" checked={soloActivosHistorial}
                onChange={e => { if (clienteHistorial) abrirHistorial(clienteHistorial, e.target.checked) }}
                className="w-4 h-4" />
              Solo activos
            </label>
          </div>

          {creditosCliente.length === 0 ? (
            <p className="text-gray-400 text-sm text-center py-4">Sin créditos registrados</p>
          ) : (
            <div className="space-y-2">
              {creditosCliente.map((cr) => (
                <div key={cr.id} className="border border-gray-200 rounded-lg overflow-hidden">
                  {/* Cabecera del crédito (click para expandir) */}
                  <button
                    onClick={() => creditoSeleccionado?.id === cr.id ? setCreditoSeleccionado(null) : verPagosCredito(cr)}
                    className={`w-full flex items-center justify-between p-3 text-left hover:bg-gray-50 transition-colors ${creditoSeleccionado?.id === cr.id ? 'bg-primary-50' : 'bg-white'}`}
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-xs font-semibold text-primary-600">{cr.numero_credito_cliente}</span>
                      <span className="text-xs text-gray-500 capitalize">{cr.tipo_credito.replace('_', ' ')}</span>
                      {cr.activo
                        ? <span className="badge-success">Activo</span>
                        : <span className="badge-danger">Cerrado</span>}
                    </div>
                    <div className="flex items-center gap-4 text-xs">
                      <div className="text-right">
                        <p className="text-gray-400">Capital</p>
                        <p className="font-semibold">{formatCOP(cr.capital_prestado)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-gray-400">Saldo</p>
                        <p className={`font-bold ${cr.saldo_capital > 0 ? 'text-danger' : 'text-success'}`}>
                          {formatCOP(cr.saldo_capital)}
                        </p>
                      </div>
                      <div className="text-right">
                        <p className="text-gray-400">Tasa</p>
                        <p className="font-mono">{formatPorcentaje(cr.tasa_interes_mensual)}</p>
                      </div>
                      <span className={`text-lg transition-transform ${creditoSeleccionado?.id === cr.id ? 'rotate-180' : ''}`}>▾</span>
                    </div>
                  </button>

                  {/* Historial de pagos (desplegable) */}
                  {creditoSeleccionado?.id === cr.id && (
                    <div className="border-t border-gray-200 bg-gray-50 p-2">
                      <div className="overflow-x-auto max-h-64">
                        <table className="w-full text-xs">
                          <thead>
                            <tr>
                              <th className="table-header">#</th>
                              <th className="table-header">Tipo</th>
                              <th className="table-header">Monto</th>
                              <th className="table-header">Capital</th>
                              <th className="table-header">Interés</th>
                              <th className="table-header">Pagado</th>
                              <th className="table-header">Fecha Máx.</th>
                              <th className="table-header">Estado</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pagosCredito.map((p, i) => (
                              <tr key={p.id} className={i % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                                <td className="table-cell font-mono">{p.numero_cuota}</td>
                                <td className="table-cell capitalize">{p.tipo_cuota.replace('_', ' ')}</td>
                                <td className="table-cell">{formatCOP(p.monto_a_pagar)}</td>
                                <td className="table-cell">{formatCOP(p.capital_a_pagar)}</td>
                                <td className="table-cell">{formatCOP(p.interes_a_pagar)}</td>
                                <td className="table-cell">{formatCOP(p.capital_pagado + p.interes_pagado)}</td>
                                <td className="table-cell">{formatFecha(p.fecha_maxima)}</td>
                                <td className="table-cell">
                                  {p.pagado ? <span className="badge-success">Pagado</span> : <span className="badge-warning">Pendiente</span>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
