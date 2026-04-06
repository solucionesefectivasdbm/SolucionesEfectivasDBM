import { useState, useEffect, useCallback } from 'react'
import { gestoresApi, usuariosApi, receptoresApi } from '@/api'
import { LoadingPage, EmptyState, Paginacion, FormField } from '@/components/ui'
import Modal from '@/components/ui/Modal'
import type { Gestor, Usuario, Receptor } from '@/types'
import { Plus, Pencil, Search } from 'lucide-react'
import { useForm } from 'react-hook-form'
import toast from 'react-hot-toast'

interface GestorForm {
  cedula: string
  nombre: string
  apellidos: string
  telefono: string
  direccion: string
  correo_electronico: string
  user_id: string
  receptor_id: string
}

export default function GestoresPage() {
  const [gestores, setGestores] = useState<Gestor[]>([])
  const [usuarios, setUsuarios] = useState<Usuario[]>([])
  const [receptores, setReceptores] = useState<Receptor[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [page, setPage] = useState(1)
  const [busqueda, setBusqueda] = useState('')
  const [loading, setLoading] = useState(true)
  const [modalForm, setModalForm] = useState(false)
  const [editando, setEditando] = useState<Gestor | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { register, handleSubmit, reset, formState: { errors } } = useForm<GestorForm>()

  const cargar = useCallback(async () => {
    setLoading(true)
    try {
      const res = await gestoresApi.listar({ page, busqueda })
      setGestores(res.data.items)
      setTotal(res.data.total)
      setPages(res.data.pages)
    } catch {
      toast.error('Error al cargar gestores')
    } finally {
      setLoading(false)
    }
  }, [page, busqueda])

  useEffect(() => { cargar() }, [cargar])

  useEffect(() => {
    // Cargar usuarios con rol gestor y receptores disponibles
    usuariosApi.listar({ page: 1 }).then(r => {
      setUsuarios(r.data.items.filter(u => u.tipo_usuario === 'gestor'))
    }).catch(() => {})

    receptoresApi.listar({ page: 1 }).then(r => {
      setReceptores(r.data.items)
    }).catch(() => {})
  }, [])

  const abrirCrear = () => {
    setEditando(null)
    reset({})
    setModalForm(true)
  }

  const abrirEditar = (g: Gestor) => {
    setEditando(g)
    reset({
      cedula: g.cedula,
      nombre: g.nombre,
      apellidos: g.apellidos,
      telefono: g.telefono,
      direccion: g.direccion,
      correo_electronico: g.correo_electronico,
      receptor_id: g.receptor_id ?? '',
    })
    setModalForm(true)
  }

  const onSubmit = async (data: GestorForm) => {
    setSubmitting(true)
    try {
      if (editando) {
        await gestoresApi.actualizar(editando.id, {
          cedula: data.cedula,
          nombre: data.nombre,
          apellidos: data.apellidos,
          telefono: data.telefono,
          direccion: data.direccion,
          correo_electronico: data.correo_electronico,
          receptor_id: data.receptor_id || null,
        })
        toast.success('Gestor actualizado')
      } else {
        await gestoresApi.crear({
          ...data,
          receptor_id: data.receptor_id || null,
        })
        toast.success('Gestor creado')
      }
      setModalForm(false)
      cargar()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Error al guardar')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-black text-primary-600">Gestores</h1>
        <button onClick={abrirCrear} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Nuevo Gestor
        </button>
      </div>

      <div className="card">
        <div className="relative max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="input pl-9"
            placeholder="Buscar por nombre..."
            value={busqueda}
            onChange={e => { setBusqueda(e.target.value); setPage(1) }}
          />
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        {loading ? <LoadingPage /> : gestores.length === 0 ? (
          <EmptyState message="No hay gestores registrados" />
        ) : (
          <>
            <table className="w-full">
              <thead>
                <tr>
                  <th className="table-header">Nombre</th>
                  <th className="table-header">Cédula</th>
                  <th className="table-header">Teléfono</th>
                  <th className="table-header">Correo</th>
                  <th className="table-header">Receptor asignado</th>
                  <th className="table-header">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {gestores.map((g, i) => (
                  <tr key={g.id} className={i % 2 === 0 ? 'table-row-even' : 'table-row-odd'}>
                    <td className="table-cell font-medium">{g.nombre} {g.apellidos}</td>
                    <td className="table-cell font-mono text-xs">{g.cedula}</td>
                    <td className="table-cell">{g.telefono}</td>
                    <td className="table-cell text-xs text-gray-500">{g.correo_electronico}</td>
                    <td className="table-cell">
                      {g.receptor
                        ? <span className="badge-success">{g.receptor.nombre}</span>
                        : <span className="badge-warning">Sin receptor</span>}
                    </td>
                    <td className="table-cell">
                      <button
                        onClick={() => abrirEditar(g)}
                        className="p-1.5 bg-primary-600 text-white rounded-lg hover:bg-primary-700"
                      >
                        <Pencil size={13} />
                      </button>
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
      <Modal
        isOpen={modalForm}
        onClose={() => setModalForm(false)}
        title={editando ? 'Editar Gestor' : 'Nuevo Gestor'}
        size="lg"
      >
        <form onSubmit={handleSubmit(onSubmit)} className="grid grid-cols-2 gap-4">

          <FormField label="Nombre" required error={errors.nombre?.message}>
            <input
              {...register('nombre', { required: 'Requerido' })}
              className={`input ${errors.nombre ? 'input-error' : ''}`}
            />
          </FormField>

          <FormField label="Apellidos" required error={errors.apellidos?.message}>
            <input
              {...register('apellidos', { required: 'Requerido' })}
              className={`input ${errors.apellidos ? 'input-error' : ''}`}
            />
          </FormField>

          <FormField label="Cédula" required error={errors.cedula?.message}>
            <input
              {...register('cedula', {
                required: 'Requerido',
                pattern: { value: /^\d{6,10}$/, message: '6-10 dígitos' },
              })}
              className={`input ${errors.cedula ? 'input-error' : ''}`}
            />
          </FormField>

          <FormField label="Teléfono" required error={errors.telefono?.message}>
            <input
              {...register('telefono', {
                required: 'Requerido',
                pattern: { value: /^\d{7,10}$/, message: '7-10 dígitos' },
              })}
              className={`input ${errors.telefono ? 'input-error' : ''}`}
            />
          </FormField>

          <FormField label="Correo electrónico" required error={errors.correo_electronico?.message}>
            <input
              {...register('correo_electronico', { required: 'Requerido' })}
              type="email"
              className={`input ${errors.correo_electronico ? 'input-error' : ''}`}
            />
          </FormField>

          <FormField label="Dirección" required error={errors.direccion?.message}>
            <input
              {...register('direccion', { required: 'Requerido' })}
              className={`input ${errors.direccion ? 'input-error' : ''}`}
            />
          </FormField>

          {/* Solo al crear: seleccionar usuario */}
          {!editando && (
            <FormField label="Usuario (rol Gestor)" required error={errors.user_id?.message}>
              <select
                {...register('user_id', { required: 'Requerido' })}
                className={`input ${errors.user_id ? 'input-error' : ''}`}
              >
                <option value="">-- Seleccionar --</option>
                {usuarios.map(u => (
                  <option key={u.id} value={u.id}>{u.username}</option>
                ))}
              </select>
            </FormField>
          )}

          <FormField label="Receptor asignado">
            <select {...register('receptor_id')} className="input">
              <option value="">-- Sin receptor --</option>
              {receptores.map(r => (
                <option key={r.id} value={r.id}>{r.nombre} — {r.cedula}</option>
              ))}
            </select>
          </FormField>

          <div className="col-span-2 flex gap-3 justify-end pt-2">
            <button type="button" onClick={() => setModalForm(false)} className="btn-ghost">
              Cancelar
            </button>
            <button type="submit" disabled={submitting} className="btn-primary">
              {submitting ? 'Guardando...' : editando ? 'Actualizar' : 'Crear'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  )
}