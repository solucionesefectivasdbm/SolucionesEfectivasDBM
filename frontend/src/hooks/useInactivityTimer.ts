/**
 * useInactivityTimer — Detecta inactividad del usuario y dispara una alerta.
 *
 * Flujo:
 * 1. Tras `inactivityMs` sin actividad (mouse, teclado, scroll, touch)
 *    se muestra el aviso (`warning = true`).
 * 2. El usuario tiene `graceMs` para confirmar que sigue activo.
 *    `confirm()` reinicia el ciclo. Si no confirma, se invoca `onTimeout`.
 *
 * Las actividades NO cuentan mientras el aviso está visible — el ciclo
 * se reanuda explícitamente con `confirm()`.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'] as const

interface Options {
  inactivityMs: number
  graceMs: number
  onTimeout: () => void
  enabled: boolean
}

export function useInactivityTimer({ inactivityMs, graceMs, onTimeout, enabled }: Options) {
  const [warning, setWarning] = useState(false)
  const [graceLeft, setGraceLeft] = useState(graceMs)

  const inGraceRef = useRef(false)
  const inactivityTimerRef = useRef<number | null>(null)
  const graceTimerRef = useRef<number | null>(null)
  const tickIntervalRef = useRef<number | null>(null)
  const onTimeoutRef = useRef(onTimeout)

  // Mantener la última versión del callback sin reiniciar el efecto.
  useEffect(() => { onTimeoutRef.current = onTimeout }, [onTimeout])

  const confirmRef = useRef<() => void>(() => {})

  useEffect(() => {
    if (!enabled) return

    const clearAll = () => {
      if (inactivityTimerRef.current) { clearTimeout(inactivityTimerRef.current); inactivityTimerRef.current = null }
      if (graceTimerRef.current) { clearTimeout(graceTimerRef.current); graceTimerRef.current = null }
      if (tickIntervalRef.current) { clearInterval(tickIntervalRef.current); tickIntervalRef.current = null }
    }

    const enterGrace = () => {
      inGraceRef.current = true
      setWarning(true)
      setGraceLeft(graceMs)
      const startedAt = Date.now()
      graceTimerRef.current = window.setTimeout(() => {
        clearAll()
        inGraceRef.current = false
        setWarning(false)
        onTimeoutRef.current()
      }, graceMs)
      tickIntervalRef.current = window.setInterval(() => {
        const elapsed = Date.now() - startedAt
        setGraceLeft(Math.max(0, graceMs - elapsed))
      }, 250)
    }

    const armInactivity = () => {
      inGraceRef.current = false
      setWarning(false)
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
      inactivityTimerRef.current = window.setTimeout(enterGrace, inactivityMs)
    }

    const onActivity = () => {
      if (inGraceRef.current) return
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
      inactivityTimerRef.current = window.setTimeout(enterGrace, inactivityMs)
    }

    confirmRef.current = () => {
      clearAll()
      armInactivity()
    }

    ACTIVITY_EVENTS.forEach(ev => window.addEventListener(ev, onActivity, { passive: true }))
    armInactivity()

    return () => {
      ACTIVITY_EVENTS.forEach(ev => window.removeEventListener(ev, onActivity))
      clearAll()
      inGraceRef.current = false
    }
  }, [enabled, inactivityMs, graceMs])

  const confirm = useCallback(() => confirmRef.current(), [])

  return { warning, graceLeft, confirm }
}
