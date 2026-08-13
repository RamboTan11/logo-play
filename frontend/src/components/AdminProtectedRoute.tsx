import { useEffect, type PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAdminAuthStore } from '../stores/useAdminAuthStore'
import { ADMIN_SESSION_INVALID_EVENT } from '../utils/adminSession'

export function AdminProtectedRoute({ children }: PropsWithChildren) {
  const location = useLocation()
  const status = useAdminAuthStore((state) => state.status)
  const invalidate = useAdminAuthStore((state) => state.invalidate)
  const checkSession = useAdminAuthStore((state) => state.checkSession)

  useEffect(() => {
    if (status === 'unknown') void checkSession()
  }, [checkSession, status])

  useEffect(() => {
    const invalidateSession = () => invalidate()
    window.addEventListener(ADMIN_SESSION_INVALID_EVENT, invalidateSession)
    return () => window.removeEventListener(ADMIN_SESSION_INVALID_EVENT, invalidateSession)
  }, [invalidate])

  if (status === 'unknown' || status === 'checking') {
    return <main className="admin-session-check" aria-live="polite"><span className="admin-session-spinner" />正在恢复后台会话...</main>
  }
  if (status !== 'authorized') {
    const from = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to={`/admin/login?return_to=${encodeURIComponent(from)}`} replace state={{ from }} />
  }
  return <>{children}</>
}
