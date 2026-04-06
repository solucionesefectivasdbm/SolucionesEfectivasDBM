import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { usuariosApi } from '@/api'
import { useAuthStore } from '@/store/authStore'
import toast from 'react-hot-toast'

interface Form { password_actual: string; password_nuevo: string; confirmar: string }

export default function CambiarPasswordPage() {
  const navigate = useNavigate()
  const { user, setUser } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const { register, handleSubmit, watch, formState: { errors } } = useForm<Form>()

  const onSubmit = async (data: Form) => {
    setLoading(true)
    try {
      await usuariosApi.cambiarMiPassword(data.password_actual, data.password_nuevo)
      setUser({ ...user!, must_change_password: false })
      toast.success('Contraseña actualizada correctamente')
      navigate('/dashboard')
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Error al cambiar la contraseña')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-primary-600 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
        <div className="bg-accent px-8 py-6 text-center">
          <h1 className="text-primary-600 font-black text-xl">Cambio de contraseña requerido</h1>
          <p className="text-primary-700 text-sm mt-1">
            Tu contraseña es temporal. Debes cambiarla para continuar.
          </p>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="px-8 py-6 space-y-4">
          <div>
            <label className="label">Contraseña temporal</label>
            <input
              {...register('password_actual', { required: 'Requerido' })}
              type="password" className="input"
            />
          </div>
          <div>
            <label className="label">Nueva contraseña</label>
            <input
              {...register('password_nuevo', {
                required: 'Requerido',
                minLength: { value: 8, message: 'Mínimo 8 caracteres' },
                pattern: {
                  value: /^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)/,
                  message: 'Debe tener mayúscula, minúscula y número',
                },
              })}
              type="password" className={`input ${errors.password_nuevo ? 'input-error' : ''}`}
            />
            {errors.password_nuevo && <p className="text-xs text-danger mt-1">{errors.password_nuevo.message}</p>}
          </div>
          <div>
            <label className="label">Confirmar nueva contraseña</label>
            <input
              {...register('confirmar', {
                required: 'Requerido',
                validate: (v) => v === watch('password_nuevo') || 'Las contraseñas no coinciden',
              })}
              type="password" className={`input ${errors.confirmar ? 'input-error' : ''}`}
            />
            {errors.confirmar && <p className="text-xs text-danger mt-1">{errors.confirmar.message}</p>}
          </div>
          <button type="submit" disabled={loading} className="w-full btn-secondary py-3">
            {loading ? 'Guardando...' : 'Cambiar contraseña'}
          </button>
        </form>
      </div>
    </div>
  )
}
