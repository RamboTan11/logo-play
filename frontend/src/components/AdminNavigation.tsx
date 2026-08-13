import { BellRing, ClipboardList, LogOut, SlidersHorizontal, UsersRound } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAdminAuthStore } from '../stores/useAdminAuthStore'

export function AdminNavigation() {
  const location = useLocation()
  const navigate = useNavigate()
  const inModelStrategy = location.pathname.startsWith('/admin/model-strategy')
  const logout = useAdminAuthStore((state) => state.logout)

  const handleLogout = async () => {
    await logout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <aside className="admin-global-nav" aria-label="管理后台导航">
      <Link className="admin-global-brand" to="/admin/tasks">管理后台</Link>
      <div className="admin-global-links">
        <Link className={`admin-global-link${location.pathname === '/admin/tasks' ? ' active' : ''}`} to="/admin/tasks">
          <ClipboardList size={16} aria-hidden="true" />
          <span>任务中心</span>
        </Link>
        <Link className={`admin-global-link${inModelStrategy ? ' active' : ''}`} to="/admin/model-strategy/models">
          <SlidersHorizontal size={16} aria-hidden="true" />
          <span>模型策略</span>
        </Link>
        <Link className={`admin-global-link${location.pathname === '/admin/customers' ? ' active' : ''}`} to="/admin/customers">
          <UsersRound size={16} aria-hidden="true" />
          <span>客户访问</span>
        </Link>
        <Link className={`admin-global-link${location.pathname === '/admin/notifications' ? ' active' : ''}`} to="/admin/notifications">
          <BellRing size={16} aria-hidden="true" />
          <span>通知配置</span>
        </Link>
      </div>
      <button className="admin-global-logout" type="button" onClick={() => void handleLogout()}>
        <LogOut size={16} aria-hidden="true" />
        <span>退出登录</span>
      </button>
    </aside>
  )
}
