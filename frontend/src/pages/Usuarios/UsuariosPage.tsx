import { useState, useEffect, useCallback } from 'react'
import { usuariosApi } from '@/api'
import { LoadingPage, EmptyState, Paginacion, ConfirmDelete, FormField } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import type { Usuario } from '@/types'
import { Plus, Pencil, Trash2, Key, Search } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'

export default function UsuariosPage() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([])
  const [total, setTotal] = useState(0); const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1); const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalForm, setModalForm] = useState(false)
  const [modalEliminar, setModalEliminar] = useState(false)
  const [modalPassword, setModalPassword] = useState(false)
  const [editando, setEditando] = useState<Usuario | null>(null)
  const [seleccionado, setSeleccionado] = useState<Usuario | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [newPassword, setNewPassword] = useState('')

  const { register, handleSubmit, reset, formState: { errors } } = useForm<any>()

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await usuariosApi.listar({ page, busqueda })
      setUsuarios(res.data.items); setTotal(res.data.total); setPages(res.data.pages)
    } catch {} finally { setLoading(false) }
  }, [page, busqueda])

  useEffect(() => { cargar() }, [cargar])

  const onSubmit = async (data: any) => {
    setSubmitting(true)
    try {
      if (editando) {
        await usuariosApi.actualizar(editando.id, { telefono: data.telefono, tipo_usuario: data.tipo_usuario, activo: data.activo })
        toast.success('Usuario actualizado')
      } else {
        await usuariosApi.crear(data)
        toast.success('Usuario creado')
      }
      setModalForm(false); cargar()
    } catch (e: any) { toast.error(e.response?.data?.detail || 'Error') }
    finally { setSubmitting(false) }
  }

  const handleEliminar = async () => {
    if (!seleccionado) return
    setSubmitting(true)
    try {
      await usuariosApi.eliminar(seleccionado.id)
      toast.success('Usuario eliminado'); setModalEliminar(false); cargar()
    } catch (e: any) { toast.error(e.response?.data?.detail || 'Error') }
    finally { setSubmitting(false) }
  }

  const handleResetPassword = async () => {
    if (!seleccionado || !newPassword) return
    setSubmitting(true)
    try {
      await usuariosApi.restablecerPassword(seleccionado.id, newPassword)
      toast.success('Contraseña restablecida'); setModalPassword(false); setNewPassword('')
    } catch (e: any) { toast.error(e.response?.data?.detail || 'Error') }
    finally { setSubmitting(false) }
  }

  const ROLES: Record<string, string> = { admin: 'Admin', registrador: 'Registrador', recaudador: 'Recaudador', gestor: 'Gestor' }
  const ROLE_COLORS: Record<string, string> = { admin: 'badge-danger', registrador: 'badge-info', recaudador: 'badge-warning', gestor: 'badge-success' }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Usuarios</h1>
        <button onClick={() => { setEditando(null); reset(); setModalForm(true) }} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Nuevo Usuario
        </button>
      </div>

      <div className="card">
        <div className="relative max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input className="input pl-9" placeholder="Buscar por username..."
            value={busqueda} onChange={e => { setBusqueda(e.target.value); setPage(1) }} />
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : usuarios.length === 0 ? <EmptyState message="Sin usuarios" /> : (
          <>
            <table className="w-full">
              <thead><tr>
                <th className="table-header">Usuario</th><th className="table-header">Rol</th>
                <th className="table-header">Teléfono</th><th className="table-header">Estado</th>
                <th className="table-header">Acciones</th>
              </tr></thead>
              <tbody>
                {usuarios.map((u, i) => (
                  <tr key={u.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                    <td className="table-cell font-semibold">{u.username}</td>
                    <td className="table-cell"><span className={ROLE_COLORS[u.tipo_usuario]}>{ROLES[u.tipo_usuario]}</span></td>
                    <td className="table-cell">{u.telefono}</td>
                    <td className="table-cell">
                      {u.activo ? <span className="badge-success">Activo</span> : <span className="badge-danger">Inactivo</span>}
                      {u.must_change_password && <span className="badge-warning ml-1">Clave temporal</span>}
                    </td>
                    <td className="table-cell">
                      <div className="flex gap-1">
                        <button onClick={() => { setEditando(u); reset({ ...u }); setModalForm(true) }}
                          className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700">
                          <Pencil size={13} />
                        </button>
                        <button onClick={() => { setSeleccionado(u); setModalPassword(true) }}
                          className="p-1.5 bg-yellow-500 text-white rounded-lg hover:opacity-90" title="Restablecer contraseña">
                          <Key size={13} />
                        </button>
                        <button onClick={() => { setSeleccionado(u); setModalEliminar(true) }}
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

      <Modal isOpen={modalForm} onClose={() => setModalForm(false)} title={editando ? 'Editar Usuario' : 'Nuevo Usuario'}>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {!editando && (
            <>
              <FormField label="Username" required error={errors.username?.message as string | undefined}>
                <input {...register('username', { required: 'Requerido' })} className={`input ${errors.username ? 'input-error' : ''}`} />
              </FormField>
              <FormField label="Contraseña" required error={errors.password?.message as string | undefined}>
                <input {...register('password', {
                  required: 'Requerido',
                  minLength: { value: 8, message: 'Mínimo 8 caracteres' },
                  pattern: { value: /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)/, message: 'Requiere mayúscula, minúscula y número' }
                })} type="password" className={`input ${errors.password ? 'input-error' : ''}`} />
              </FormField>
            </>
          )}
          <FormField label="Teléfono" required error={errors.telefono?.message as string | undefined}>
            <input {...register('telefono', {
              required: 'Requerido',
              pattern: { value: /^\d{7,10}$/, message: '7-10 dígitos' }
            })} className={`input ${errors.telefono ? 'input-error' : ''}`} />
          </FormField>
          <FormField label="Rol" required>
            <select {...register('tipo_usuario', { required: true })} className="input">
              <option value="">-- Seleccionar --</option>
              <option value="admin">Administrador</option>
              <option value="registrador">Registrador</option>
              <option value="recaudador">Recaudador</option>
              <option value="gestor">Gestor</option>
            </select>
          </FormField>
          {editando && (
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" {...register('activo')} className="w-4 h-4" />
              Usuario activo
            </label>
          )}
          <div className="flex gap-3 justify-end pt-2">
            <button type="button" onClick={() => setModalForm(false)} className="btn-ghost">Cancelar</button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : editando ? 'Actualizar' : 'Crear'}
            </button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={modalPassword} onClose={() => setModalPassword(false)} title="Restablecer Contraseña" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-gray-600">Nueva contraseña temporal para <strong>{seleccionado?.username}</strong>.</p>
          <input type="password" className="input" placeholder="Nueva contraseña"
            value={newPassword} onChange={e => setNewPassword(e.target.value)} />
          <div className="flex gap-3 justify-end">
            <button onClick={() => setModalPassword(false)} className="btn-ghost">Cancelar</button>
            <button onClick={handleResetPassword} disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : 'Restablecer'}
            </button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={modalEliminar} onClose={() => setModalEliminar(false)} title="Eliminar Usuario" size="sm">
        <ConfirmDelete message={`¿Eliminar al usuario ${seleccionado?.username}?`}
          onConfirm={handleEliminar} onCancel={() => setModalEliminar(false)} loading={submitting} />
      </Modal>
    </div>
  )
}
