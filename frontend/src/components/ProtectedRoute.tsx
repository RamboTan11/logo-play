import { useEffect, type PropsWithChildren } from 'react'
import { Navigate } from 'react-router-dom'
import { useAccessStore } from '../stores/useAccessStore'

const sessionRefreshIntervalMs = 15_000

export function ProtectedRoute({ children }: PropsWithChildren) {
  const status = useAccessStore((state) => state.status)
  const checkSession = useAccessStore((state) => state.checkSession)
  useEffect(() => {
    if (status === 'unknown') void checkSession()
  }, [checkSession, status])

  useEffect(() => {
    if (status !== 'authorized') return
    const refresh = () => { void checkSession({ silent: true }) }
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    const timer = window.setInterval(refresh, sessionRefreshIntervalMs)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
    }
  }, [checkSession, status])

  if (status === 'unknown' || status === 'checking') {
    return <main className="session-check-page" aria-live="polite"><span className="session-check-spinner" />正在恢复访问...</main>
  }
  return status === 'authorized' ? <>{children}</> : <Navigate to="/access" replace />
}
