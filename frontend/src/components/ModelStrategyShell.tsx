import { ChevronRight, ListChecks, PanelsTopLeft, WandSparkles } from 'lucide-react'
import type { PropsWithChildren, ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { AdminNavigation } from './AdminNavigation'
import { GlobalToast } from './GlobalToast'

interface ModelStrategyShellProps extends PropsWithChildren {
  title: string
  description: string
  actions?: ReactNode
}

const strategyTabs = [
  { to: '/admin/model-strategy/models', label: '模型列表', icon: ListChecks },
  { to: '/admin/model-strategy/batch', label: '批量生图', icon: PanelsTopLeft },
  { to: '/admin/model-strategy/single-edit', label: '单图编辑', icon: WandSparkles },
]

export function ModelStrategyShell({ title, description, actions, children }: ModelStrategyShellProps) {
  return (
    <div className="internal-shell">
      <AdminNavigation />
      <main className="model-strategy-page">
        <header className="model-strategy-page-head">
          <div className="model-strategy-heading">
            <nav className="model-strategy-breadcrumb" aria-label="面包屑">
              <Link to="/admin/tasks">管理后台</Link>
              <ChevronRight size={14} aria-hidden="true" />
              <span>模型策略</span>
              <ChevronRight size={14} aria-hidden="true" />
              <b>{title}</b>
            </nav>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          {actions && <div className="model-strategy-head-actions">{actions}</div>}
        </header>
        <nav className="model-strategy-tabs" aria-label="模型策略页面">
          {strategyTabs.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `model-strategy-tab${isActive ? ' active' : ''}`}>
              <Icon size={16} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        {children}
        <GlobalToast />
      </main>
    </div>
  )
}
