import { ArrowRight, Check, ChevronDown, LoaderCircle, Plus, X } from 'lucide-react'
import { type ClipboardEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClientShell } from '../components/ClientShell'
import { GenerationWaitingState } from '../components/GenerationWaitingState'
import { useGenerationStore } from '../stores/useGenerationStore'
import { rememberLastCreationPath } from '../utils/clientNavigation'
import {
  GenerationApiError,
  restoreGenerationSourceAsset,
  uploadGenerationSourceAsset,
} from '../services/generationsService'
import { useToastStore } from '../stores/useToastStore'
import { useClientLanguage } from '../i18n/useClientLanguage'
import {
  GenerationSourceUploadLifecycle,
  initialGenerationSourceUploadState,
} from '../utils/generationSourceUpload'
import {
  clearGenerationSourceRecovery,
  readGenerationSourceRecovery,
  writeGenerationSourceRecovery,
} from '../utils/generationSourceRecovery'

const MAX_SOURCE_IMAGE_BYTES = 10 * 1024 * 1024
const SOURCE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

export function CreationPage() {
  const { t } = useClientLanguage()
  const navigate = useNavigate()
  const suffixControlRef = useRef<HTMLDivElement>(null)
  const suffixTriggerRef = useRef<HTMLButtonElement>(null)
  const [isSuffixOpen, setIsSuffixOpen] = useState(false)
  const [sourceUploadState, setSourceUploadState] = useState(initialGenerationSourceUploadState)
  const sourceInputRef = useRef<HTMLInputElement>(null)
  const sourceRestorationAttemptedRef = useRef(false)
  const {
    domainLabel,
    domainSuffix,
    sourceImageAssetId,
    userReferenceRequirement,
    error,
    isProcessing,
    isRegenerating,
    completedGeneration,
    shouldRedirectToResults,
    setDomainLabel,
    setDomainSuffix,
    setSourceImageAssetId,
    setUserReferenceRequirement,
    clearSourceImage,
    generate,
    restoreActiveGeneration,
  } = useGenerationStore()
  const showToast = useToastStore((state) => state.showToast)

  const [sourceUpload] = useState(() => new GenerationSourceUploadLifecycle({
      createObjectUrl: (file) => URL.createObjectURL(file),
      revokeObjectUrl: (url) => URL.revokeObjectURL(url),
      onError: (message) => showToast(t(message)),
      onStateChange: (state) => {
        setSourceUploadState(state)
        if (!state.assetId && !state.isUploading) clearSourceImage()
        else setSourceImageAssetId(state.assetId)
        if (state.assetId && state.filename) {
          writeGenerationSourceRecovery({
            assetId: state.assetId,
            filename: state.filename,
            requirement: useGenerationStore.getState().userReferenceRequirement.trim(),
          })
        } else {
          clearGenerationSourceRecovery()
        }
      },
      upload: uploadGenerationSourceAsset,
    }))

  const { filename: sourceFilename, isUploading: isUploadingSource, previewUrl: sourcePreviewUrl } = sourceUploadState

  useEffect(() => {
    rememberLastCreationPath('/create')
    restoreActiveGeneration()
  }, [restoreActiveGeneration])

  useEffect(() => {
    if (sourceRestorationAttemptedRef.current) return
    sourceRestorationAttemptedRef.current = true
    const metadata = readGenerationSourceRecovery()
    if (!metadata || sourceUploadState.assetId || sourceUploadState.isUploading) return
    setUserReferenceRequirement(metadata.requirement)
    void restoreGenerationSourceAsset(metadata.assetId).then((content) => {
      sourceUpload.restore(metadata.assetId, metadata.filename, content)
    }).catch((error: unknown) => {
      if (
        error instanceof GenerationApiError
        && (error.code === 'invalid_source_image' || error.code === 'source_image_not_found')
      ) {
        clearGenerationSourceRecovery()
        clearSourceImage()
        sourceUpload.clear()
      }
    })
  }, [clearSourceImage, setUserReferenceRequirement, sourceUpload, sourceUploadState.assetId, sourceUploadState.isUploading])

  useEffect(() => {
    if (sourceImageAssetId || !sourceUploadState.assetId) return
    sourceUpload.clear()
  }, [sourceImageAssetId, sourceUpload, sourceUploadState.assetId])

  useEffect(() => {
    if (!sourceImageAssetId || !sourceFilename) return
    writeGenerationSourceRecovery({
      assetId: sourceImageAssetId,
      filename: sourceFilename,
      requirement: userReferenceRequirement.trim(),
    })
  }, [sourceFilename, sourceImageAssetId, userReferenceRequirement])

  useEffect(() => {
    if (shouldRedirectToResults) navigate('/results')
  }, [navigate, shouldRedirectToResults])

  useEffect(() => {
    if (!isSuffixOpen) return
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!suffixControlRef.current?.contains(event.target as Node)) setIsSuffixOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setIsSuffixOpen(false)
      suffixTriggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutsideClick)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [isSuffixOpen])

  const notifyGenerationBusy = () => showToast(t('正在执行生图任务，请稍后。'))

  const selectSuffix = (suffix: typeof domainSuffix) => {
    if (isRegenerating) {
      notifyGenerationBusy()
      return
    }
    setDomainSuffix(suffix)
    setIsSuffixOpen(false)
    window.setTimeout(() => suffixTriggerRef.current?.focus(), 0)
  }

  useEffect(() => () => sourceUpload.dispose(), [sourceUpload])

  const chooseSourceImage = async (file: File | undefined) => {
    if (isRegenerating) {
      notifyGenerationBusy()
      return
    }
    if (!file || sourceUploadState.isUploading) return
    if (!SOURCE_IMAGE_TYPES.has(file.type)) {
      showToast(t('仅支持 PNG、JPEG 或 WebP 图片。'))
      return
    }
    if (file.size > MAX_SOURCE_IMAGE_BYTES) {
      showToast(t('视觉参考图片不能超过 10 MB。'))
      return
    }
    await sourceUpload.choose(file)
  }

  const handlePaste = (event: ClipboardEvent<HTMLElement>) => {
    const imageItem = Array.from(event.clipboardData.items).find(
      (item) => item.kind === 'file' && SOURCE_IMAGE_TYPES.has(item.type),
    )
    const pastedFile = imageItem?.getAsFile()
    if (!pastedFile) return
    event.preventDefault()
    const extension = pastedFile.type === 'image/png' ? '.png' : pastedFile.type === 'image/webp' ? '.webp' : '.jpg'
    const namedFile = pastedFile.name ? pastedFile : new File([pastedFile], `pasted-reference${extension}`, { type: pastedFile.type })
    void chooseSourceImage(namedFile)
  }

  const removeSourceImage = () => {
    if (sourceUploadState.isUploading || isRegenerating) {
      if (isRegenerating) notifyGenerationBusy()
      return
    }
    sourceUpload.remove()
    clearSourceImage()
    clearGenerationSourceRecovery()
    if (sourceInputRef.current) sourceInputRef.current.value = ''
  }

  const hasCompletedResults = completedGeneration !== null

  return (
    <ClientShell>
      <main className="client-main creation-main minimal-domain-main" onPaste={handlePaste}>
        <h1 className="sr-only">{t('Logo 创作')}</h1>
        {hasCompletedResults && <button
          className="creation-results-return icon-tooltip"
          type="button"
          aria-label={t('查看生成结果')}
          title={t('查看生成结果')}
          data-tooltip={t('查看生成结果')}
          onClick={() => navigate('/results')}
        >
          <ArrowRight size={19} strokeWidth={2.2} aria-hidden="true" />
        </button>}
        {isProcessing ? <section className="minimal-domain-stage creation-generating-stage" aria-busy="true">
          <GenerationWaitingState title={t('正在生成 Logo 方案')} description={t('正在根据您的域名探索设计方向，生成结果会自动显示')} />
        </section> : <section className="minimal-domain-stage" aria-live="polite">
          <label className="sr-only" htmlFor="brand-domain-entry">{t('品牌域名')}</label>
          <div className="minimal-domain-field">
            <input
              id="brand-domain-entry"
              name="brand-domain-entry"
              className="domain-input"
              type="text"
              autoComplete="off"
              spellCheck={false}
              data-1p-ignore="true"
              value={domainLabel}
              placeholder={t('请输入域名前缀，如 igame')}
              onChange={(event) => setDomainLabel(event.target.value)}
              readOnly={isRegenerating}
              onClick={() => { if (isRegenerating) notifyGenerationBusy() }}
            />
            <div className="domain-suffix-control" ref={suffixControlRef}>
              <button
                ref={suffixTriggerRef}
                className="domain-suffix-trigger"
                type="button"
                aria-label={t('域名后缀')}
                aria-haspopup="listbox"
                aria-expanded={isSuffixOpen}
                aria-controls="domain-suffix-options"
                onClick={() => { if (isRegenerating) notifyGenerationBusy(); else setIsSuffixOpen((open) => !open) }}
                onKeyDown={(event) => {
                  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
                  event.preventDefault()
                  setIsSuffixOpen(true)
                }}
              >
                <span>{domainSuffix}</span>
                <ChevronDown className={isSuffixOpen ? 'open' : ''} size={16} aria-hidden="true" />
              </button>
              {isSuffixOpen && <ul className="domain-suffix-menu" id="domain-suffix-options" role="listbox" aria-label={t('选择域名后缀')}>
                {(['.com', '.game', '.win', '.app'] as const).map((suffix) => <li role="none" key={suffix}>
                  <button type="button" role="option" aria-selected={suffix === domainSuffix} onClick={() => selectSuffix(suffix)}>
                    <span>{suffix}</span>
                    {suffix === domainSuffix && <Check size={15} aria-hidden="true" />}
                  </button>
                </li>)}
              </ul>}
            </div>
          </div>
          {error && <div className="inline-error">{t(error)}</div>}
          <div className="creation-source-control">
            <div className="creation-source-preview-row">
              <div
                className={`creation-source-preview${!sourcePreviewUrl ? ' is-empty' : ''}${isUploadingSource ? ' is-uploading' : ''}`}
                title={isUploadingSource ? t('正在上传视觉参考') : sourceFilename ?? t('上传视觉参考')}
                aria-busy={isUploadingSource}
              >
                {sourcePreviewUrl ? <img src={sourcePreviewUrl} alt={sourceFilename ?? t('视觉参考')} /> : <label className="creation-source-trigger" title={t('上传视觉参考（选填）')} aria-label={t('上传视觉参考（选填）')} onClick={() => { if (isRegenerating) notifyGenerationBusy() }}>
                  <Plus size={21} aria-hidden="true" />
                  <small>{t('选填')}</small>
                  <input ref={sourceInputRef} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" disabled={isUploadingSource || isRegenerating} onChange={(event) => { void chooseSourceImage(event.target.files?.[0]); event.currentTarget.value = '' }} />
                </label>}
                {isUploadingSource && <div className="creation-source-upload-status" role="status" aria-label={t('正在上传视觉参考')}>
                  <LoaderCircle size={23} aria-hidden="true" />
                  <span>{t('上传中')}</span>
                </div>}
                {!isUploadingSource && sourceImageAssetId && <button className="creation-source-preview-remove" type="button" title={t('删除视觉参考')} aria-label={t('删除视觉参考')} onClick={removeSourceImage}><X size={14} aria-hidden="true" /></button>}
              </div>
              <div className="creation-source-side">
                <label className="creation-reference-requirement"><span className="sr-only">{t('创作要求（选填）')}</span><textarea aria-label={t('创作要求（选填）')} value={userReferenceRequirement} placeholder={t('请输入创作要求，例如：仅使用 mmg 这三个文字进行设计（可留空）。')} readOnly={isRegenerating} onClick={() => { if (isRegenerating) notifyGenerationBusy() }} onChange={(event) => setUserReferenceRequirement(event.target.value)} /></label>
              </div>
            </div>
          </div>
          <footer className="minimal-domain-action">
            <div>
              <button className="primary" type="button" disabled={!sourceUpload.canGenerate()} onClick={() => { if (isRegenerating) notifyGenerationBusy(); else void generate() }}>{t('生成创意初稿')}</button>
              <p>{t('本次将生成平面创意初稿，采用后由我们继续优化为最终成品。')}</p>
            </div>
          </footer>
        </section>}
      </main>
    </ClientShell>
  )
}
