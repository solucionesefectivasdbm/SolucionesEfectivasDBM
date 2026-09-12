/**
 * utils/apiErrors.ts — Mapeo uniforme de errores de Axios a mensajes de UI.
 * Nunca muestra el literal "Error"; precedencia: sesión expirada > detail del
 * backend > timeout > red > fallback del caller.
 */
import type { AxiosError } from 'axios'

export const AUTH_REDIRECT_REASON_KEY = 'auth_redirect_reason'

/** Marca que la sesión expiró (refresh silencioso falló). Solo desde axios.ts. */
export function marcarSesionExpirada(): void {
  try {
    sessionStorage.setItem(AUTH_REDIRECT_REASON_KEY, 'session_expired')
  } catch {
    // sessionStorage puede no estar disponible — no bloquear el flujo.
  }
}

/** Lee si hay una razón de expiración pendiente. No limpia la clave. */
export function leerSesionExpirada(): boolean {
  try {
    return sessionStorage.getItem(AUTH_REDIRECT_REASON_KEY) === 'session_expired'
  } catch {
    return false
  }
}

/** Traduce un error de Axios a mensaje de UI, o `null` si no debe mostrarse toast. */
export function mensajeError(e: unknown, fallback: string): string | null {
  if (leerSesionExpirada()) {
    return null
  }

  const err = e as AxiosError<{ detail?: unknown }>

  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    const mensajes = detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? String((item as { msg: unknown }).msg) : null))
      .filter((msg): msg is string => Boolean(msg))
    if (mensajes.length > 0) {
      return mensajes.join(', ')
    }
  }

  if (err?.code === 'ECONNABORTED') {
    return 'La solicitud tardó demasiado. Intenta de nuevo.'
  }

  if (err?.code === 'ERR_NETWORK' || !err?.response) {
    return 'Sin conexión con el servidor. Verifica tu red e intenta de nuevo.'
  }

  return fallback
}

/**
 * True cuando el error es el rechazo de la petición original tras un refresh
 * fallido con 401 (sesión expirada) — el caller debe evitar refetch/efectos
 * adicionales porque el interceptor ya está redirigiendo a /login.
 */
export function esErrorSesionExpirada(e: unknown): boolean {
  return (e as AxiosError)?.response?.status === 401 && leerSesionExpirada()
}
