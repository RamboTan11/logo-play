import { useEffect, useRef, useState } from 'react'
import { useClientLanguage } from '../i18n/useClientLanguage'

const adoptTooltip = '采用此方案后，我们会继续完善细节，并向你交付最终图片'

export function AdoptionConfirmDialog({
  domain,
  initialSuggestion,
  isChange,
  isSubmitting,
  errorMessage,
  onClose,
  onConfirm,
}: {
  domain: string
  initialSuggestion: string
  isChange: boolean
  isSubmitting: boolean
  errorMessage?: string | null
  onClose: () => void
  onConfirm: (suggestion: string) => void
}) {
  const { t } = useClientLanguage()
  const [suggestion, setSuggestion] = useState(initialSuggestion)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [isSubmitting, onClose])

  return (
    <div className="saved-logo-adopt-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !isSubmitting) onClose() }}>
      <section className="saved-logo-adopt-dialog" role="dialog" aria-modal="true" aria-labelledby="saved-adopt-title" aria-describedby="saved-adopt-description">
        <header><div><h2 id="saved-adopt-title">{t(isChange ? '确认变更方案' : '确认采用方案')}</h2><p id="saved-adopt-description">{domain}</p></div><button type="button" aria-label={t('关闭采用确认')} disabled={isSubmitting} onClick={onClose}>×</button></header>
        <div className="saved-logo-adopt-body">
          {isChange && <p className="adoption-change-warning">{t('已有提交的方案，请确认是否发起变更')}</p>}
          {errorMessage && <p className="adoption-confirm-error" role="alert">{errorMessage}</p>}
          <label className="adoption-note-field"><span>{t('人工精修建议（选填）')}</span><textarea ref={inputRef} value={suggestion} disabled={isSubmitting} placeholder={t('可输入你的精修建议')} onChange={(event) => setSuggestion(event.target.value)} /></label>
        </div>
        <footer><button className="secondary" type="button" disabled={isSubmitting} onClick={onClose}>{t('取消')}</button><div className="adopt-tooltip"><button className="primary" type="button" disabled={isSubmitting} onClick={() => onConfirm(suggestion)}>{t(isSubmitting ? '提交中...' : isChange ? '确认变更' : '确认采用')}</button><span>{t(adoptTooltip)}</span></div></footer>
      </section>
    </div>
  )
}
