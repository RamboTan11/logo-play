import { useEffect, useRef, useState } from 'react'
import { CachedImage } from './CachedImage'
import { LogoArtwork } from './LogoArtwork'
import { GenerationWaitingState } from './GenerationWaitingState'
import { useClientLanguage } from '../i18n/useClientLanguage'

export interface ResultEditVersion {
  id: string
  imageUrl: string | null
}

interface ResultEditDialogProps {
  domain: string
  source: ResultEditVersion
  variant: number
  isPageBusy: boolean
  onClose: () => void
  onGenerate: (instruction: string) => Promise<ResultEditVersion | null>
  onUse: (version: ResultEditVersion) => void | Promise<void>
}

export function ResultEditDialog({
  domain,
  source,
  variant,
  isPageBusy,
  onClose,
  onGenerate,
  onUse,
}: ResultEditDialogProps) {
  const { t } = useClientLanguage()
  const [instruction, setInstruction] = useState('')
  const [generated, setGenerated] = useState<ResultEditVersion | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const generateButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    generateButtonRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isGenerating && !isPageBusy) onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [isGenerating, isPageBusy, onClose])

  const generate = async () => {
    if (isGenerating || isPageBusy) return
    setIsGenerating(true)
    setError(null)
    try {
      const next = await onGenerate(instruction)
      if (next) setGenerated(next)
      else setError(t('新版本生成失败，请稍后重试。'))
    } catch {
      setError(t('新版本生成失败，请稍后重试。'))
    } finally {
      setIsGenerating(false)
    }
  }

  const useGenerated = async () => {
    if (!generated || isGenerating || isPageBusy) return
    setError(null)
    try {
      await onUse(generated)
    } catch {
      setError(t('收藏方案更新失败，请稍后重试。'))
    }
  }

  const renderArtwork = (version: ResultEditVersion, label: string, artworkVariant: number) => (
    <div className="result-edit-artwork" aria-label={label}>
      {version.imageUrl
        ? <CachedImage src={version.imageUrl} alt={label} thumbnail />
        : <LogoArtwork variant={artworkVariant} domain={domain} />}
    </div>
  )

  return (
    <div className="result-edit-modal" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !isGenerating && !isPageBusy) onClose()
    }}>
      <section className="result-edit-dialog" role="dialog" aria-modal="true" aria-labelledby="result-edit-title">
        <header>
          <div><h2 id="result-edit-title">{t('编辑优化')}</h2><p>{domain}</p></div>
          <button type="button" aria-label={t('关闭编辑优化')} disabled={isGenerating || isPageBusy} onClick={onClose}>×</button>
        </header>
        <div className="result-edit-body" aria-busy={isGenerating}>
          {!generated ? <>
            <section><h3>{t('原图')}</h3>{renderArtwork(source, t('原图'), variant)}</section>
            <label className="adoption-note-field result-edit-instruction"><span>{t('优化需求（选填）')}</span><textarea value={instruction} disabled={isGenerating || isPageBusy} placeholder={t('可输入您的优化需求，默认重新生成当前相似风格的 logo 图。')} onChange={(event) => setInstruction(event.target.value)} /></label>
          </> : <section className="result-edit-comparison" aria-label={t('原图与新图对比')}>
            <div><h3>{t('原图')}</h3>{renderArtwork(source, t('原图'), variant)}</div>
            <div><h3>{t('新图')}</h3>{renderArtwork(generated, t('新图'), variant + 1)}</div>
          </section>}
          {error && <p className="result-edit-error" role="alert">{error}</p>}
          {isGenerating && <div className="result-edit-generating-overlay">
            <GenerationWaitingState title={t('正在生成新版本')} description={t('正在按优化要求生成新方案，结果会自动显示')} />
          </div>}
        </div>
        <footer>
          {generated && <button className="secondary" type="button" disabled={isGenerating || isPageBusy} onClick={() => void generate()}>{t('重新生成')}</button>}
          {generated
            ? <button className="primary" type="button" disabled={isGenerating || isPageBusy} onClick={() => void useGenerated()}>{t('选用')}</button>
            : <button ref={generateButtonRef} className="primary" type="button" disabled={isGenerating || isPageBusy} onClick={() => void generate()}>{t(isGenerating ? '生成中...' : '编辑优化')}</button>}
        </footer>
      </section>
    </div>
  )
}
