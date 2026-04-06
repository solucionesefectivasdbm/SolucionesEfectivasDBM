/**
 * api/axios.ts — Instancia de Axios con interceptores JWT.
 *
 * DECISIÓN TÉCNICA: El access token vive en memoria (Zustand store),
 * nunca en localStorage. El refresh token viaja en HttpOnly cookie
 * automáticamente — el navegador la adjunta sin que JS la vea.
 *
 * El interceptor de respuesta detecta 401 y reintenta con refresh
 * automáticamente antes de redirigir al login.
 */
import axios from 'axios'
import { useAuthStore } from '@/store/authStore'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  withCredentials: true, // Necesario para enviar la cookie de refresh token
  headers: { 'Content-Type': 'application/json' },
})

// Adjuntar access token a cada request
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Manejar 401: intentar refresh antes de redirigir al login
let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: unknown) => void }> = []

const processQueue = (error: unknown, token: string | null = null) => {
  failedQueue.forEach((p) => {
    if (error) p.reject(error)
    else p.resolve(token!)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return api(originalRequest)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post(
          `${API_URL}/api/v1/auth/refresh`,
          {},
          { withCredentials: true }
        )
        const newToken = data.access_token
        useAuthStore.getState().setAccessToken(newToken)
        useAuthStore.getState().setUser(data.user)
        processQueue(null, newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return api(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        useAuthStore.getState().logout()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)
