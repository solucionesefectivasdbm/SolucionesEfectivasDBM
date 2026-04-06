/**
 * store/authStore.ts — Estado global de autenticación.
 *
 * DECISIÓN TÉCNICA: El access token SOLO vive en este store (memoria).
 * Al refrescar la página se pierde, pero el interceptor de Axios
 * automáticamente lo renueva con el refresh token (HttpOnly cookie).
 * Nunca usamos localStorage para el token.
 */
import { create } from 'zustand'
import type { Usuario } from '@/types'

interface AuthState {
  accessToken: string | null
  user: Usuario | null
  isAuthenticated: boolean
  setAccessToken: (token: string) => void
  setUser: (user: Usuario) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,

  setAccessToken: (token) =>
    set({ accessToken: token, isAuthenticated: true }),

  setUser: (user) =>
    set({ user }),

  logout: () =>
    set({ accessToken: null, user: null, isAuthenticated: false }),
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
    canVerReportes: role === 'admin' || role === 'registrador' || role === 'recaudador',
    canGestionarUsuarios: role === 'admin',
    canGestionarReceptores: role === 'admin',
  }
}
