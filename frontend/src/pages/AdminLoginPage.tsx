import axios from 'axios'
import { LockKeyhole, UserRound } from 'lucide-react'
import { FormEvent, useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { loginAdmin } from '../services/adminAuthService'
import { useAdminAuthStore } from '../stores/useAdminAuthStore'

export function AdminLoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const status = useAdminAuthStore((state) => state.status)
  const authorize = useAdminAuthStore((state) => state.authorize)
  const checkSession = useAdminAuthStore((state) => state.checkSession)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const usernameRef = useRef<HTMLInputElement>(null)
  const requestedFrom = typeof location.state === 'object' && location.state && 'from' in location.state
    ? String(location.state.from)
    : ''
  const returnTo = searchParams.get('return_to') ?? ''
  const from = [requestedFrom, returnTo].find((candidate) => (
    candidate.startsWith('/admin/') && !candidate.startsWith('//')
  )) ?? '/admin/tasks'

  useEffect(() => {
    if (status === 'unknown') void checkSession()
  }, [checkSession, status])
  useEffect(() => { usernameRef.current?.focus() }, [])

  if (status === 'authorized') return <Navigate to={from} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError('请输入账号和密码')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      await loginAdmin(username.trim(), password)
      authorize()
      navigate(from, { replace: true })
    } catch (requestError) {
      setError(axios.isAxiosError(requestError) && requestError.response?.status === 401
        ? '账号或密码错误'
        : '暂时无法登录，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  return <main className="admin-login-page">
    <section className="admin-login-panel">
      <header><span>内部管理</span><h1>登录管理后台</h1></header>
      <form onSubmit={(event) => void submit(event)} noValidate>
        <label><span>账号</span><div className="admin-login-field"><UserRound size={17} aria-hidden="true" /><input ref={usernameRef} autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} disabled={submitting} /></div></label>
        <label><span>密码</span><div className="admin-login-field"><LockKeyhole size={17} aria-hidden="true" /><input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={submitting} /></div></label>
        <p className={`admin-login-error${error ? ' visible' : ''}`} role={error ? 'alert' : undefined}>{error}</p>
        <button className="admin-login-submit" type="submit" disabled={submitting}>{submitting && <span className="admin-button-spinner" aria-hidden="true" />}{submitting ? '正在登录' : '登录'}</button>
      </form>
    </section>
  </main>
}
