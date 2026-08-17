import { useEffect, useRef } from 'react'
import { useClientLanguage } from '../i18n/useClientLanguage'

export function BatchReplaceConfirmDialog({ onClose, onConfirm }: { onClose: () => void; onConfirm: () => void }) {
  const { t } = useClientLanguage()
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    confirmRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return <div className="batch-replace-modal" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className="batch-replace-dialog" role="dialog" aria-modal="true" aria-labelledby="batch-replace-title">
      <h2 id="batch-replace-title">{t('换一批')}</h2>
      <p>{t('当前选择将被丢弃')}</p>
      <footer><button className="secondary" type="button" onClick={onClose}>{t('取消')}</button><button ref={confirmRef} className="primary" type="button" onClick={onConfirm}>{t('换一批')}</button></footer>
    </section>
  </div>
}
