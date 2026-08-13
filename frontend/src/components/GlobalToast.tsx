import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useClientLanguage } from '../i18n/useClientLanguage'
import { useToastStore } from '../stores/useToastStore'

export function GlobalToast() {
  const { t } = useClientLanguage()
  const location = useLocation()
  const message = useToastStore((state) => state.message)
  const action = useToastStore((state) => state.action)
  const clearToast = useToastStore((state) => state.clearToast)

  useEffect(() => {
    clearToast()
  }, [clearToast, location.key])

  return message ? (
    <div className="global-toast" role="status" aria-live="polite">
      <span>{t(message)}</span>
      {action ? <><Link to={action.to} onClick={clearToast}>{t(action.label)}</Link>{action.suffix ? t(action.suffix) : null}</> : null}
    </div>
  ) : null
}
