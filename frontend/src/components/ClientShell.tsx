import type { PropsWithChildren } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { GlobalToast } from './GlobalToast'
import { DeliveryRatingFloater } from './DeliveryRatingFloater'
import { getLastCreationPath } from '../utils/clientNavigation'
import { useClientLanguage } from '../i18n/useClientLanguage'
import { LanguageSwitcher } from './LanguageSwitcher'

export function ClientShell({ children }: PropsWithChildren) {
  const { pathname } = useLocation()
  const { t } = useClientLanguage()
  const isCreation = pathname === '/create' || pathname === '/results'
  const isMyPlans = pathname.startsWith('/my-plans')

  return (
    <div className="client-shell">
      <header className="topbar">
        <div className="brand"><i />{t('Logo素材生成')}</div>
        <nav className="topnav" aria-label={t('客户侧导航')}>
          <Link className={`nav-link ${isCreation ? 'active' : ''}`} to={getLastCreationPath()}>{t('创作')}</Link>
          <Link className={`nav-link ${isMyPlans ? 'active' : ''}`} to="/my-plans">{t('我的方案')}</Link>
        </nav>
        <LanguageSwitcher />
      </header>
      {children}
      <DeliveryRatingFloater />
      <GlobalToast />
    </div>
  )
}
