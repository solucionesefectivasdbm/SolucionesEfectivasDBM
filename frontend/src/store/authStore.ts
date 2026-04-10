/**
 * store/authStore.ts — Estado global de autenticación.
 *
 * DECISIÓN TÉCNICA: El access token SOLO vive en este store (memoria).
 * Al refrescar la página se pierde, pero `init()` lo renueva automáticamente
 * usando el refresh token (HttpOnly cookie). Nunca usamos localStorage
 * para el token.
 *
 * `initializing` arranca en true: la app muestra un spinner mientras
 * intenta restaurar la sesión con /auth/refresh. Si la cookie existe
 * y es válida, el usuario continúa sin ver el login.
 */
import axios from 'axios'
import { create } from 'zustand'
import type { Usuario } from '@/types'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

interface AuthState {
  accessToken: string | null
  user: Usuario | null
  isAuthenticated: boolean
  initializing: boolean          // true mientras intentamos restaurar sesión
  setAccessToken: (token: string) => void
  setUser: (user: Usuario) => void
  logout: () => void
  init: () => Promise<void>      // intenta renovar sesión al cargar la app
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,
  initializing: true,

  setAccessToken: (token) =>
    set({ accessToken: token, isAuthenticated: true }),

  setUser: (user) =>
    set({ user }),

  logout: () =>
    set({ accessToken: null, user: null, isAuthenticated: false }),

  init: async () => {
    // Si ya tenemos token, no hace falta refrescar
    if (get().accessToken) {
      set({ initializing: false })
      return
    }
    try {
      const { data } = await axios.post(
        `${API_URL}/api/v1/auth/refresh`,
        {},
        { withCredentials: true },
      )
      set({
        accessToken: data.access_token,
        user: data.user,
        isAuthenticated: true,
        initializing: false,
      })
    } catch {
      // Cookie expirada o inexistente → usuario debe loguearse
      set({ initializing: false })
    }
  },
}))

// Hook de permisos — centraliza el control de acceso en el frontend
export const usePermissions = () => {
  const user = useAuthStore((s) => s.user)
  const role = user?.tipo_usuario

  return {
    isAdmin: role === 'admin',
    isRegistrador: role === 'registrador',
    isRecaudador: role === 'recaudador',
    isGestor: role === 'gestor',
    canCreate: role === 'admin' || role === 'registrador',
    canEdit: role === 'admin',
    canDelete: role === 'admin',
    canValidarPago: role === 'admin' || role === 'recaudador',
    canRegistrarPago: role === 'admin' || role === 'registrador',
    canVerReportes: role === 'admin',
    canGestionarUsuarios: role === 'admin',
    canGestionarReceptores: role === 'admin',
  }
}
