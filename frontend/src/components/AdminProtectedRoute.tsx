import { useEffect, type PropsWithChildren } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAdminAuthStore } from '../stores/useAdminAuthStore'

export function AdminProtectedRoute({ children }: PropsWithChildren) {
  const location = useLocation()
  const status = useAdminAuthStore((state) => state.status)
  const checkSession = useAdminAuthStore((state) => state.checkSession)

  useEffect(() => {
    if (status === 'unknown') void checkSession()
  }, [checkSession, status])

  if (status === 'unknown' || status === 'checking') {
    return <main className="admin-session-check" aria-live="polite"><span className="admin-session-spinner" />正在恢复后台会话...</main>
  }
  if (status !== 'authorized') {
    return <Navigate to="/admin/login" replace state={{ from: `${location.pathname}${location.search}${location.hash}` }} />
  }
  return <>{children}</>
}
