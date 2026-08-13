import { Link } from 'react-router-dom'
import { useToastStore } from '../stores/useToastStore'

export function GlobalToast() {
  const message = useToastStore((state) => state.message)
  const action = useToastStore((state) => state.action)
  const clearToast = useToastStore((state) => state.clearToast)

  return message ? (
    <div className="global-toast" role="status" aria-live="polite">
      <span>{message}</span>
      {action ? <><Link to={action.to} onClick={clearToast}>{action.label}</Link>{action.suffix}</> : null}
    </div>
  ) : null
}
