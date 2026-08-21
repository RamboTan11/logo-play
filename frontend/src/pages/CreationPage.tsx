import { ArrowRight, Check, ChevronDown, ChevronLeft, ChevronRight, LoaderCircle, Plus, X } from 'lucide-react'
import { type ClipboardEvent, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClientShell } from '../components/ClientShell'
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
import {
  getGenerationStyleCatalog,
} from '../services/batchGenerationPolicyService'
import type { GenerationStyleCatalogStyleDto } from '../types/modelStrategy'

const MAX_SOURCE_IMAGE_BYTES = 10 * 1024 * 1024
const SOURCE_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp'])

function filenameWithoutExtension(filename: string): string {
  return filename.replace(/\.[^/.]+$/, '')
}

function resolveShowcaseUrl(styleId: string, image: { asset_id: string; content_url: string }): string {
  const contentUrl = image.content_url.trim()
  if (contentUrl) {
    return contentUrl.startsWith('/api/')
      ? `${import.meta.env.BASE_URL}${contentUrl.slice(1)}`
      : contentUrl
  }
  return `${import.meta.env.BASE_URL}api/v1/generation-style-catalog/styles/${encodeURIComponent(styleId)}/showcase-images/${encodeURIComponent(image.asset_id)}/content?thumbnail=true`
}

async function preloadShowcaseImage(url: string, signal: AbortSignal): Promise<string | null> {
  try {
    const response = await fetch(url, { cache: 'force-cache', credentials: 'include', signal })
    if (!response.ok) return null
    const objectUrl = URL.createObjectURL(await response.blob())
    const image = new Image()
    image.src = objectUrl
    try {
      await image.decode()
      return objectUrl
    } catch {
      URL.revokeObjectURL(objectUrl)
      return null
    }
  } catch {
    return null
  }
}

export function CreationPage() {
  const { t } = useClientLanguage()
  const navigate = useNavigate()
  const suffixControlRef = useRef<HTMLDivElement>(null)
  const suffixTriggerRef = useRef<HTMLButtonElement>(null)
  const [isSuffixOpen, setIsSuffixOpen] = useState(false)
  const [selectedStyleIds, setSelectedStyleIds] = useState<string[]>([])
  const [showcaseIndexes, setShowcaseIndexes] = useState<Record<string, number>>({})
  const [styleCatalogView, setStyleCatalogView] = useState<{
    styles: GenerationStyleCatalogStyleDto[]
    urls: Record<string, string>
  }>({ styles: [], urls: {} })
  const [styleCatalogError, setStyleCatalogError] = useState<string | null>(null)
  const showcaseObjectUrlsRef = useRef<string[]>([])
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
  const { styles: styleCatalog, urls: showcaseUrls } = styleCatalogView

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
    let active = true
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 5000)
    void getGenerationStyleCatalog().then(async (catalog) => {
      if (!active) return
      const styles = catalog.styles
      const resolved = styles.flatMap((style) => style.showcase_images.map((image) => [image.asset_id, resolveShowcaseUrl(style.id, image)] as const))
      const preloaded = await Promise.all(resolved.map(async ([assetId, url]) => [
        assetId,
        await preloadShowcaseImage(url, controller.signal),
      ] as const))
      if (!active) {
        preloaded.forEach(([, objectUrl]) => { if (objectUrl) URL.revokeObjectURL(objectUrl) })
        return
      }
      if (preloaded.some(([, objectUrl]) => !objectUrl)) {
        preloaded.forEach(([, objectUrl]) => { if (objectUrl) URL.revokeObjectURL(objectUrl) })
        setStyleCatalogView({ styles: [], urls: {} })
        setStyleCatalogError('风格样图暂时无法加载，您仍可直接生成。')
        return
      }
      const urls = Object.fromEntries(preloaded) as Record<string, string>
      showcaseObjectUrlsRef.current.forEach((objectUrl) => URL.revokeObjectURL(objectUrl))
      showcaseObjectUrlsRef.current = Object.values(urls)
      setStyleCatalogView({ styles, urls })
      setStyleCatalogError(null)
      setSelectedStyleIds((current) => current.filter((id) => styles.some((style) => style.id === id)))
      setShowcaseIndexes((current) => Object.fromEntries(styles.map((style) => [
        style.id,
        Math.min(Math.max(current[style.id] ?? 0, 0), Math.max(style.showcase_images.length - 1, 0)),
      ])))
    }).catch(() => {
      if (!active) return
      setStyleCatalogView({ styles: [], urls: {} })
      setStyleCatalogError('风格目录暂时无法加载，您仍可直接生成。')
    }).finally(() => window.clearTimeout(timeout))
    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [])

  useEffect(() => () => {
    showcaseObjectUrlsRef.current.forEach((objectUrl) => URL.revokeObjectURL(objectUrl))
    showcaseObjectUrlsRef.current = []
  }, [])

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
  const selectedStyleNames = styleCatalog
    .filter((style) => selectedStyleIds.includes(style.id))
    .map((style) => style.name)

  const toggleStyle = (styleId: string) => {
    const isSelected = selectedStyleIds.includes(styleId)
    const nextSelectedStyleIds = isSelected
      ? selectedStyleIds.filter((id) => id !== styleId)
      : [...selectedStyleIds, styleId]
    setSelectedStyleIds(nextSelectedStyleIds)
  }

  const changeShowcase = (style: GenerationStyleCatalogStyleDto, direction: -1 | 1) => {
    setShowcaseIndexes((current) => ({
      ...current,
      [style.id]: Math.min(
        style.showcase_images.length - 1,
        Math.max(0, (current[style.id] ?? 0) + direction),
      ),
    }))
  }

  const handleGenerate = async () => {
    if (isProcessing || isRegenerating) {
      notifyGenerationBusy()
      return
    }
    await generate(selectedStyleIds)
    const state = useGenerationStore.getState()
    if (state.isProcessing && !state.isRegenerating) navigate('/results')
  }

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
        <section className="minimal-domain-stage creation-card" aria-live="polite">
          <header className="creation-card-intro">
            <span>{t('从品牌域名开始')}</span>
            <h2>{t('快速生成您的创意 logo')}</h2>
          </header>
          <label className="creation-domain-label" htmlFor="brand-domain-entry"><b>{t('必填')}</b><span>{t('品牌域名')}</span></label>
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
              readOnly={isProcessing || isRegenerating}
              onClick={() => { if (isProcessing || isRegenerating) notifyGenerationBusy() }}
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
                onClick={() => { if (isProcessing || isRegenerating) notifyGenerationBusy(); else setIsSuffixOpen((open) => !open) }}
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
          <p className="creation-domain-hint">{t('默认使用您输入域名中的 2～3 个字符设计')}</p>
          {error && <div className="inline-error">{t(error)}</div>}
          <section className="creation-style-picker" aria-labelledby="creation-style-picker-title">
            <div className="creation-style-heading">
              <span>{t('选填')}</span>
              <h3 id="creation-style-picker-title">{t('猜您喜欢')}</h3>
            </div>
            <div className="creation-style-catalog" role="group" aria-label={t('选择喜欢的 Logo 类型')}>
              {styleCatalog.map((style) => {
                const showcaseIndex = showcaseIndexes[style.id] ?? 0
                const showcase = style.showcase_images[showcaseIndex]
                const showcaseFilename = showcase?.filename?.trim()
                  ? filenameWithoutExtension(showcase.filename.trim())
                  : ''
                const isSelected = selectedStyleIds.includes(style.id)
                if (!showcase) return null
                return <article className={`creation-style-card${isSelected ? ' active' : ''}`} key={style.id}>
                  <button
                    className="creation-style-card-title"
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => toggleStyle(style.id)}
                  >{style.name}</button>
                  <div className="creation-showcase-stage">
                    {showcaseUrls[showcase.asset_id]
                      ? <button
                        className="creation-showcase-image-button"
                        type="button"
                        aria-pressed={isSelected}
                        aria-label={`${t('选择喜欢的 Logo 类型')}：${style.name}`}
                        onClick={() => toggleStyle(style.id)}
                      ><img src={showcaseUrls[showcase.asset_id]} alt={style.name} /></button>
                      : <div className="creation-style-showcase-loading" aria-label={t('正在加载样图')} />}
                    <button
                      className="creation-showcase-nav creation-showcase-previous"
                      type="button"
                      aria-label={t('上一张样图')}
                      disabled={showcaseIndex === 0}
                      onClick={() => changeShowcase(style, -1)}
                    ><ChevronLeft size={18} aria-hidden="true" /></button>
                    <button
                      className="creation-showcase-nav creation-showcase-next"
                      type="button"
                      aria-label={t('下一张样图')}
                      disabled={showcaseIndex === style.showcase_images.length - 1}
                      onClick={() => changeShowcase(style, 1)}
                    ><ChevronRight size={18} aria-hidden="true" /></button>
                    <small className="creation-showcase-count">{showcaseIndex + 1}/{style.showcase_images.length}</small>
                  </div>
                  {showcaseFilename && <small className="creation-showcase-name" title={showcaseFilename}>{showcaseFilename}</small>}
                </article>
              })}
            </div>
            {selectedStyleNames.length > 0 && <p className="creation-style-selection" role="status">{t('已选择')} {selectedStyleNames.join('、')}</p>}
            {styleCatalogError && <p className="creation-style-catalog-error" role="status">{t(styleCatalogError)}</p>}
          </section>
          <div className="creation-source-control">
            <div className="creation-source-preview-row">
              <div
                className={`creation-source-preview${!sourcePreviewUrl ? ' is-empty' : ''}${isUploadingSource ? ' is-uploading' : ''}`}
                title={isUploadingSource ? t('正在上传视觉参考') : sourceFilename ?? t('上传视觉参考')}
                aria-busy={isUploadingSource}
              >
                {sourcePreviewUrl ? <img src={sourcePreviewUrl} alt={sourceFilename ?? t('视觉参考')} /> : <label className="creation-source-trigger" title={t('上传视觉参考（选填）')} aria-label={t('上传视觉参考（选填）')} onClick={() => { if (isProcessing || isRegenerating) notifyGenerationBusy() }}>
                  <Plus size={21} aria-hidden="true" />
                  <small>{t('参考图')}</small>
                  <input ref={sourceInputRef} className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" disabled={isUploadingSource || isProcessing || isRegenerating} onChange={(event) => { void chooseSourceImage(event.target.files?.[0]); event.currentTarget.value = '' }} />
                </label>}
                {isUploadingSource && <div className="creation-source-upload-status" role="status" aria-label={t('正在上传视觉参考')}>
                  <LoaderCircle size={23} aria-hidden="true" />
                  <span>{t('上传中')}</span>
                </div>}
                {!isUploadingSource && sourceImageAssetId && <button className="creation-source-preview-remove" type="button" title={t('删除视觉参考')} aria-label={t('删除视觉参考')} onClick={removeSourceImage}><X size={14} aria-hidden="true" /></button>}
              </div>
              <div className="creation-source-side">
                <label className="creation-reference-requirement"><span className="creation-reference-label">{t('创作要求（选填）')}</span><textarea aria-label={t('创作要求（选填）')} value={userReferenceRequirement} placeholder={t('请输入创作要求，例如：仅使用 mmg 这三个文字进行设计（可留空）。')} readOnly={isProcessing || isRegenerating} onClick={() => { if (isProcessing || isRegenerating) notifyGenerationBusy() }} onChange={(event) => setUserReferenceRequirement(event.target.value)} /></label>
              </div>
            </div>
          </div>
          <footer className="minimal-domain-action">
            <div>
              <b>{t('将为您生成创意初稿')}</b>
              <p>{t('采用后由我们继续优化为最终成品')}</p>
            </div>
            <button className="primary" type="button" disabled={!sourceUpload.canGenerate()} onClick={() => void handleGenerate()}>{t('生成创意初稿')}</button>
          </footer>
        </section>
      </main>
    </ClientShell>
  )
}
