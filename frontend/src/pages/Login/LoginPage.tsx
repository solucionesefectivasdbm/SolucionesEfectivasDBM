import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { Eye, EyeOff, Lock, User } from 'lucide-react'
import { authApi } from '@/api'
import { useAuthStore } from '@/store/authStore'
import toast from 'react-hot-toast'

interface LoginForm {
  username: string
  password: string
}

export default function LoginPage() {
  const navigate = useNavigate()
  const { setAccessToken, setUser } = useAuthStore()
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)

  const { register, handleSubmit, formState: { errors } } = useForm<LoginForm>()

  const onSubmit = async (data: LoginForm) => {
    setLoading(true)
    try {
      const res = await authApi.login(data.username, data.password)
      setAccessToken(res.data.access_token)
      setUser(res.data.user)
      if (res.data.user.must_change_password) {
        navigate('/cambiar-password')
      } else {
        navigate('/dashboard')
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Credenciales incorrectas'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-primary-600 flex items-center justify-center p-4">
      {/* Fondo decorativo */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-primary-500 opacity-50" />
        <div className="absolute -bottom-32 -left-32 w-96 h-96 rounded-full bg-primary-700 opacity-50" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full border border-primary-400 opacity-20" />
      </div>

      <div className="relative w-full max-w-md">
        {/* Card */}
        <div className="bg-white rounded-2xl shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="bg-primary-600 px-8 py-8 text-center">
            <div className="w-16 h-16 bg-accent rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg">
              <span className="text-primary-600 font-black text-2xl">SE</span>
            </div>
            <h1 className="text-white font-black text-2xl">Soluciones Efectivas DBM</h1>
            <p className="text-primary-200 text-sm mt-1">Gestión de Cartera de Préstamos</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit(onSubmit)} className="px-8 py-8 space-y-5">
            <div>
              <label className="label">Usuario</label>
              <div className="relative">
                <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  {...register('username', { required: 'El usuario es obligatorio' })}
                  className={`input pl-9 ${errors.username ? 'input-error' : ''}`}
                  placeholder="Nombre de usuario"
                  autoFocus
                />
              </div>
              {errors.username && (
                <p className="text-xs text-danger mt-1">{errors.username.message}</p>
              )}
            </div>

            <div>
              <label className="label">Contraseña</label>
              <div className="relative">
                <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  {...register('password', { required: 'La contraseña es obligatoria' })}
                  type={showPass ? 'text' : 'password'}
                  className={`input pl-9 pr-10 ${errors.password ? 'input-error' : ''}`}
                  placeholder="Contraseña"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                >
                  {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {errors.password && (
                <p className="text-xs text-danger mt-1">{errors.password.message}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full btn-primary py-3 text-base"
            >
              {loading ? 'Ingresando...' : 'Ingresar'}
            </button>

            <p className="text-center text-xs text-gray-400">
              ¿Olvidaste tu contraseña? Contacta al Administrador.
            </p>
          </form>
        </div>
      </div>
    </div>
  )
}
