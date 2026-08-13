import { LoaderCircle } from 'lucide-react'
import { useClientLanguage } from '../i18n/useClientLanguage'

interface GenerationWaitingStateProps {
  title: string
  description: string
}

export function GenerationWaitingState({ title, description }: GenerationWaitingStateProps) {
  const { t } = useClientLanguage()
  return <div className="generation-waiting-state" role="status" aria-live="polite">
    <div className="generation-waiting-symbol" aria-hidden="true"><LoaderCircle size={30} strokeWidth={1.8} /></div>
    <div className="generation-waiting-copy">
      <b className="loading-copy">{title}<span className="loading-ellipsis" aria-hidden="true" /></b>
      <span>{description}</span>
      <small>{t('预计需 1～3 分钟，请稍等')}</small>
    </div>
    <div className="generation-waiting-track" aria-hidden="true"><span /></div>
  </div>
}
