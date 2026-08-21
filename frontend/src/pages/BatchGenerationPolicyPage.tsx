import { Archive, ChevronDown, ChevronUp, FileImage, ImagePlus, LoaderCircle, Pencil, Plus, Send, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ModelStrategyShell } from '../components/ModelStrategyShell'
import { StrategyDialog } from '../components/StrategyDialog'
import {
  BatchGenerationPolicyServiceError,
  getBatchGenerationPolicy,
  getReferenceImageContent,
  getReferenceImageAssets,
  publishBatchGenerationPolicy,
  saveBatchGenerationPolicyDraft,
  uploadShowcaseImage,
  uploadReferenceImage,
} from '../services/batchGenerationPolicyService'
import { getModelConnections } from '../services/modelConnectionsService'
import { useToastStore } from '../stores/useToastStore'
import type {
  BatchPolicyPayloadDto,
  BatchPromptTemplateDto,
  ModelConnectionDto,
  ReferenceImageAssetDto,
  StrategyValidationErrorDto,
} from '../types/modelStrategy'
import {
  applyBatchGenerationCountGates,
  canSelectBatchGenerationCount,
  isCompleteBatchTemplate,
  visibleBatchTemplates,
} from '../utils/batchPolicyUi'

interface StyleFormState {
  id: string | null
  name: string
  showcaseImages: ShowcaseImageDraft[]
}

interface ShowcaseImageDraft {
  key: string
  assetId?: string
  file?: File
  previewUrl?: string
  filename: string
}

interface TemplateFormState {
  styleId: string
  templateId: string | null
  name: string
  referenceImages: TemplateReferenceDraft[]
  positivePrompt: string
  negativePrompt: string
  initialSignature: string
}

interface TemplateReferenceDraft {
  key: string
  assetId?: string
  file?: File
  previewUrl?: string
  contentHash?: string
  filename: string
}

type DraftSaveState = 'idle' | 'saving' | 'saved' | 'error'

function nextDraftId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

function showcaseAssetContentUrl(assetId: string): string {
  return `${import.meta.env.BASE_URL}api/v1/model-strategy-assets/showcase-images/${encodeURIComponent(assetId)}/content`
}

async function referenceImageContentHash(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function templateFormSignature(form: Omit<TemplateFormState, 'initialSignature'>): string {
  return JSON.stringify({
    name: form.name,
    positivePrompt: form.positivePrompt,
    negativePrompt: form.negativePrompt,
    references: form.referenceImages.map((item) => item.assetId ?? item.key),
  })
}

function referencedAssetIds(policy: BatchPolicyPayloadDto): string[] {
  return [...new Set(policy.styles.flatMap(
    (style) => style.templates.flatMap((template) => template.reference_images),
  ))]
}

function formatStrategyTimestamp(value: string | null): string {
  if (!value) return '尚未发布'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function formatPublishError(error: StrategyValidationErrorDto): string {
  const match = error.field.match(/^styles\[(\d+)\](?:\.templates\[(\d+)\])?\./)
  if (!match) return error.message
  const styleLabel = `风格 ${String(Number(match[1]) + 1).padStart(2, '0')}`
  const templateLabel = match[2] === undefined ? '' : ` · 第 ${Number(match[2]) + 1} 个模板`
  return `${styleLabel}${templateLabel}：${error.message}`
}

function useReferencePreviewUrls(assetIds: string[]): Record<string, string> {
  const [previewUrls, setPreviewUrls] = useState<Record<string, string>>({})
  const previewUrlsRef = useRef<Record<string, string>>({})
  const assetIdsKey = JSON.stringify([...new Set(assetIds.filter(Boolean))].sort())

  useEffect(() => {
    const desiredIds = JSON.parse(assetIdsKey) as string[]
    const desired = new Set(desiredIds)
    const retained: Record<string, string> = {}
    Object.entries(previewUrlsRef.current).forEach(([assetId, url]) => {
      if (desired.has(assetId)) retained[assetId] = url
      else URL.revokeObjectURL(url)
    })
    previewUrlsRef.current = retained

    let active = true
    void Promise.resolve().then(() => {
      if (active) setPreviewUrls({ ...previewUrlsRef.current })
    })
    desiredIds.filter((assetId) => !retained[assetId]).forEach((assetId) => {
      void getReferenceImageContent(assetId).then((content) => {
        const url = URL.createObjectURL(content)
        if (!active || !desired.has(assetId)) {
          URL.revokeObjectURL(url)
          return
        }
        if (previewUrlsRef.current[assetId]) {
          URL.revokeObjectURL(url)
          return
        }
        const next = { ...previewUrlsRef.current, [assetId]: url }
        previewUrlsRef.current = next
        setPreviewUrls(next)
      }).catch(() => undefined)
    })
    return () => { active = false }
  }, [assetIdsKey])

  useEffect(() => () => {
    Object.values(previewUrlsRef.current).forEach((url) => URL.revokeObjectURL(url))
    previewUrlsRef.current = {}
  }, [])

  return previewUrls
}

export function BatchGenerationPolicyPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [draft, setDraft] = useState<BatchPolicyPayloadDto | null>(null)
  const [connections, setConnections] = useState<ModelConnectionDto[]>([])
  const [assets, setAssets] = useState<ReferenceImageAssetDto[]>([])
  const [publishErrors, setPublishErrors] = useState<StrategyValidationErrorDto[]>([])
  const [isPublishing, setIsPublishing] = useState(false)
  const [draftSaveState, setDraftSaveState] = useState<DraftSaveState>('idle')
  const [lastPublishedAt, setLastPublishedAt] = useState<string | null>(null)
  const [draftUpdatedAt, setDraftUpdatedAt] = useState<string | null>(null)
  const [expandedStyleIds, setExpandedStyleIds] = useState<Set<string>>(() => new Set())
  const [styleForm, setStyleForm] = useState<StyleFormState | null>(null)
  const [templateForm, setTemplateForm] = useState<TemplateFormState | null>(null)
  const [modalError, setModalError] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [isSelectingReferences, setIsSelectingReferences] = useState(false)
  const referenceSelectionBusyRef = useRef(false)
  const draftRef = useRef<BatchPolicyPayloadDto | null>(null)
  const draftSaveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const draftSaveSequenceRef = useRef(0)
  const [loadError, setLoadError] = useState('')
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [policy, modelConnections] = await Promise.all([
          getBatchGenerationPolicy(),
          getModelConnections(),
        ])
        const referenceAssets = await getReferenceImageAssets(referencedAssetIds(policy.draft_seed))
        if (!active) return
        draftRef.current = policy.draft_seed
        setDraft(policy.draft_seed)
        setLastPublishedAt(policy.last_published_at)
        setDraftUpdatedAt(policy.draft_updated_at)
        setDraftSaveState(policy.draft_updated_at ? 'saved' : 'idle')
        setConnections(modelConnections)
        setAssets(referenceAssets)
      } catch (error) {
        if (active) setLoadError(error instanceof Error ? error.message : '读取批量策略失败')
      }
    }
    void load()
    return () => { active = false }
  }, [])

  const verifiedConnections = useMemo(() => connections.filter((connection) => connection.verified_capabilities.some((capability) => capability.capability === 'image_to_image' && capability.verified)), [connections])
  const totalGenerationCount = draft?.styles.reduce((sum, style) => sum + style.generation_count, 0) ?? 0
  const draftPreviewAssetIds = draft ? referencedAssetIds(draft) : []
  const previewAssetIds = templateForm
    ? [...draftPreviewAssetIds, ...templateForm.referenceImages.flatMap((item) => item.assetId ? [item.assetId] : [])]
    : draftPreviewAssetIds
  const previewUrls = useReferencePreviewUrls(previewAssetIds)

  const persistDraft = async (nextDraft: BatchPolicyPayloadDto, optimistic = true): Promise<boolean> => {
    if (optimistic) {
      draftRef.current = nextDraft
      setDraft(nextDraft)
    }
    setPublishErrors([])
    setDraftSaveState('saving')
    const sequence = ++draftSaveSequenceRef.current
    const operation = draftSaveQueueRef.current.then(() => saveBatchGenerationPolicyDraft(nextDraft))
    draftSaveQueueRef.current = operation.then(() => undefined, () => undefined)
    try {
      const saved = await operation
      if (!optimistic) {
        draftRef.current = nextDraft
        setDraft(nextDraft)
      }
      if (sequence === draftSaveSequenceRef.current) {
        setDraftUpdatedAt(saved.saved_at)
        setDraftSaveState('saved')
      }
      return true
    } catch (error) {
      if (sequence === draftSaveSequenceRef.current) setDraftSaveState('error')
      showToast(error instanceof Error ? error.message : '草稿保存失败')
      return false
    }
  }

  const discardTemplateForm = () => {
    templateForm?.referenceImages.forEach((item) => { if (item.previewUrl) URL.revokeObjectURL(item.previewUrl) })
    setTemplateForm(null)
    setModalError('')
  }

  const closeTemplateForm = () => {
    if (!templateForm || isUploading || isSelectingReferences || referenceSelectionBusyRef.current) return
    const { initialSignature, ...current } = templateForm
    if (templateFormSignature(current) !== initialSignature && !window.confirm('放弃未保存的修改？')) return
    discardTemplateForm()
  }

  const closeStyleForm = () => {
    styleForm?.showcaseImages.forEach((image) => {
      if (image.previewUrl) URL.revokeObjectURL(image.previewUrl)
    })
    setStyleForm(null)
    setModalError('')
  }

  const openStyleForm = (style?: BatchPolicyPayloadDto['styles'][number]) => {
    const form: StyleFormState = {
      id: style?.id ?? null,
      name: style?.name ?? '',
      showcaseImages: (style?.showcase_image_asset_ids ?? []).map((assetId) => ({
      key: assetId,
      assetId,
      previewUrl: showcaseAssetContentUrl(assetId),
      filename: '展示样图',
    })),
    }
    setStyleForm(form)
    setModalError('')
  }

  const chooseShowcaseImages = (files: File[]) => {
    if (!styleForm || !files.length || isUploading) return
    const remaining = 3 - styleForm.showcaseImages.length
    if (remaining <= 0) {
      showToast('最多支持 3 张展示样图，请先删除后再添加。')
      return
    }
    const valid = files.filter((file) => ['image/jpeg', 'image/png', 'image/webp'].includes(file.type) && file.size <= 12 * 1024 * 1024)
    if (valid.length !== files.length) showToast('仅支持 12MB 以内的 JPEG、PNG 或 WebP 图片。')
    const additions = valid.slice(0, remaining).map((file) => ({
      key: nextDraftId('pending-showcase'),
      file,
      previewUrl: URL.createObjectURL(file),
      filename: file.name,
    }))
    if (!additions.length) return
    setStyleForm((current) => current ? {
      ...current,
      showcaseImages: [...current.showcaseImages, ...additions],
    } : current)
    if (valid.length > remaining) showToast(`最多添加 3 张展示样图，已保留前 ${remaining} 张。`)
  }

  const removeShowcaseImage = (key: string) => {
    setStyleForm((current) => {
      if (!current) return current
      const image = current.showcaseImages.find((item) => item.key === key)
      if (image?.previewUrl) URL.revokeObjectURL(image.previewUrl)
      return { ...current, showcaseImages: current.showcaseImages.filter((item) => item.key !== key) }
    })
  }

  const applyStyleForm = async () => {
    const currentDraft = draftRef.current
    if (!currentDraft || !styleForm || isUploading) return
    const duplicate = styleForm.name.trim() && currentDraft.styles.some((style) => style.id !== styleForm.id && style.name.trim() === styleForm.name.trim())
    if (duplicate) { setModalError('已存在同名风格类型。'); return }
    setIsUploading(true)
    let uploaded: ReferenceImageAssetDto[] = []
    try {
      uploaded = await Promise.all(styleForm.showcaseImages.flatMap((image) => image.file ? [uploadShowcaseImage(image.file)] : []))
    } catch (error) {
      setIsUploading(false)
      setModalError(error instanceof Error ? error.message : '上传展示样图失败')
      return
    }
    let uploadIndex = 0
    const showcaseImageAssetIds = styleForm.showcaseImages.flatMap((image) => {
      if (image.assetId) return [image.assetId]
      const asset = uploaded[uploadIndex++]
      return asset ? [asset.id] : []
    })
    const styles = styleForm.id
      ? currentDraft.styles.map((style) => style.id === styleForm.id ? {
        ...style,
        name: styleForm.name,
        description: '',
        showcase_image_asset_ids: showcaseImageAssetIds,
      } : style)
      : [...currentDraft.styles, {
        id: nextDraftId('draft-style'),
        name: styleForm.name,
        description: '',
        showcase_image_asset_ids: showcaseImageAssetIds,
        generation_count: 0,
        templates: [],
      }]
    const saved = await persistDraft({ ...currentDraft, styles }, false)
    setIsUploading(false)
    if (!saved) { setModalError('草稿保存失败，请重试。'); return }
    closeStyleForm()
  }

  const openTemplateForm = (styleId: string, template?: BatchPromptTemplateDto) => {
    const referenceImages = (template?.reference_images ?? []).map((assetId) => ({
      key: assetId,
      assetId,
      contentHash: assets.find((asset) => asset.id === assetId)?.content_hash,
      filename: assets.find((asset) => asset.id === assetId)?.filename ?? '参考图',
    }))
    const form = {
      styleId,
      templateId: template?.id ?? null,
      name: template?.name ?? '',
      referenceImages,
      positivePrompt: template?.positive_prompt ?? '为 {{域名}} 设计',
      negativePrompt: template?.negative_prompt ?? '',
    }
    setTemplateForm({ ...form, initialSignature: templateFormSignature(form) })
    setModalError('')
  }

  const applyTemplateForm = async () => {
    const currentDraft = draftRef.current
    if (!currentDraft || !templateForm || isUploading || isSelectingReferences) return
    const style = currentDraft.styles.find((item) => item.id === templateForm.styleId)
    if (!style) return
    const duplicate = templateForm.name.trim() && style.templates.some((template) => template.id !== templateForm.templateId && template.name.trim() === templateForm.name.trim())
    if (duplicate) { setModalError('该风格下已存在同名模板。'); return }
    setIsUploading(true)
    setModalError('')
    let uploadedAssets: ReferenceImageAssetDto[] = []
    try {
      uploadedAssets = await Promise.all(templateForm.referenceImages.flatMap((item) => item.file ? [uploadReferenceImage(item.file)] : []))
    } catch (error) {
      setModalError(error instanceof Error ? error.message : '上传参考图失败')
      setIsUploading(false)
      return
    }
    let uploadIndex = 0
    const resolvedReferences = templateForm.referenceImages.map((item) => {
      if (item.assetId) return item
      const uploaded = uploadedAssets[uploadIndex++]
      return uploaded ? {
        key: uploaded.id,
        assetId: uploaded.id,
        previewUrl: item.previewUrl,
        contentHash: uploaded.content_hash,
        filename: uploaded.filename,
      } : item
    })
    setTemplateForm((current) => current ? { ...current, referenceImages: resolvedReferences } : null)
    setAssets((current) => [...current, ...uploadedAssets.filter((asset) => !current.some((item) => item.id === asset.id))])
    const referenceImages = resolvedReferences.flatMap((item) => item.assetId ? [item.assetId] : [])
    const template: BatchPromptTemplateDto = {
      id: templateForm.templateId ?? nextDraftId('draft-template'),
      name: templateForm.name,
      reference_images: referenceImages,
      positive_prompt: templateForm.positivePrompt,
      negative_prompt: templateForm.negativePrompt,
    }
    const templates = templateForm.templateId
      ? style.templates.map((item) => item.id === templateForm.templateId ? template : item)
      : [...style.templates, template]
    const nextDraft = applyBatchGenerationCountGates({
      ...currentDraft,
      styles: currentDraft.styles.map((item) => item.id === style.id ? { ...item, templates } : item),
    })
    const saved = await persistDraft(nextDraft, false)
    setIsUploading(false)
    if (!saved) { setModalError('图片已上传，但草稿保存失败，请重试。'); return }
    discardTemplateForm()
  }

  const chooseReferenceImages = async (files: File[]) => {
    if (!templateForm || isUploading || referenceSelectionBusyRef.current || !files.length) return
    referenceSelectionBusyRef.current = true
    setIsSelectingReferences(true)
    try {
      const remaining = 8 - templateForm.referenceImages.length
      if (remaining <= 0) { showToast('最多支持 8 张参考图，请先删除后再添加。'); return }
      const invalid = files.find((file) => !['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 12 * 1024 * 1024)
      if (invalid) { showToast('仅支持 12MB 以内的 JPEG、PNG 或 WebP 图片。'); return }
      let selected: Array<{ file: File; contentHash: string }>
      try {
        selected = await Promise.all(files.map(async (file) => ({ file, contentHash: await referenceImageContentHash(file) })))
      } catch {
        showToast('图片读取失败，请重新选择。')
        return
      }
      const knownHashes = new Set(templateForm.referenceImages.flatMap((item) => item.contentHash ? [item.contentHash] : []))
      const uniqueSelected = selected.filter((item) => {
        if (knownHashes.has(item.contentHash)) return false
        knownHashes.add(item.contentHash)
        return true
      })
      const additions = uniqueSelected.slice(0, remaining).map(({ file, contentHash }) => ({
        key: nextDraftId('pending-reference'),
        file,
        contentHash,
        previewUrl: URL.createObjectURL(file),
        filename: file.name,
      }))
      if (!additions.length) return
      setTemplateForm((current) => current ? { ...current, referenceImages: [...current.referenceImages, ...additions] } : null)
      if (uniqueSelected.length > remaining) showToast(`最多添加 8 张参考图，已保留前 ${remaining} 张。`)
    } finally {
      referenceSelectionBusyRef.current = false
      setIsSelectingReferences(false)
    }
  }

  const removeReferenceImage = (key: string) => {
    setTemplateForm((current) => {
      if (!current) return current
      const item = current.referenceImages.find((reference) => reference.key === key)
      if (item?.file && item.previewUrl) URL.revokeObjectURL(item.previewUrl)
      return { ...current, referenceImages: current.referenceImages.filter((reference) => reference.key !== key) }
    })
  }

  const updateGenerationCount = async (styleId: string, generationCount: number) => {
    const currentDraft = draftRef.current
    if (!currentDraft) return
    if (!canSelectBatchGenerationCount(currentDraft, styleId, generationCount)) {
      showToast('所有风格本轮合计最多生成 9 张图片。')
      return
    }
    await persistDraft({
      ...currentDraft,
      styles: currentDraft.styles.map((style) => style.id === styleId
        ? { ...style, generation_count: style.templates.some(isCompleteBatchTemplate) ? generationCount : 0 }
        : style),
    })
  }

  const deleteStyle = async (styleId: string) => {
    const currentDraft = draftRef.current
    if (!currentDraft || !window.confirm('删除该风格及其全部提示词模板？')) return
    const saved = await persistDraft({ ...currentDraft, styles: currentDraft.styles.filter((style) => style.id !== styleId) })
    if (saved) setExpandedStyleIds((current) => {
      const next = new Set(current)
      next.delete(styleId)
      return next
    })
  }

  const deleteTemplate = async (styleId: string, templateId: string) => {
    const currentDraft = draftRef.current
    if (!currentDraft || !window.confirm('删除该提示词模板？')) return
    const next = {
      ...currentDraft,
      styles: currentDraft.styles.map((style) => style.id === styleId ? { ...style, templates: style.templates.filter((template) => template.id !== templateId) } : style),
    }
    await persistDraft(applyBatchGenerationCountGates(next))
  }

  const toggleStyleTemplates = (styleId: string) => {
    setExpandedStyleIds((current) => {
      const next = new Set(current)
      if (next.has(styleId)) next.delete(styleId)
      else next.add(styleId)
      return next
    })
  }

  const publish = async () => {
    const currentDraft = draftRef.current
    if (!currentDraft || isPublishing) return
    setIsPublishing(true)
    setPublishErrors([])
    try {
      const saved = await persistDraft(currentDraft)
      if (!saved) return
      await publishBatchGenerationPolicy()
      const policy = await getBatchGenerationPolicy()
      draftRef.current = policy.draft_seed
      setDraft(policy.draft_seed)
      setLastPublishedAt(policy.last_published_at)
      setDraftUpdatedAt(policy.draft_updated_at)
      showToast('已按当前配置策略发布')
    } catch (error) {
      const validationErrors = error instanceof BatchGenerationPolicyServiceError ? error.validationErrors : []
      setPublishErrors(validationErrors)
      showToast(error instanceof Error ? error.message : '发布失败')
      window.setTimeout(() => document.querySelector<HTMLElement>('.batch-style-row.has-error, .scene-model-field.has-error')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
    } finally {
      setIsPublishing(false)
    }
  }

  if (!draft) return <ModelStrategyShell title="批量生图" description="按风格轮选提示词模板，并根据模板是否配置参考图自动选择生成模式。"><p className="strategy-loading">{loadError || '正在加载...'}</p></ModelStrategyShell>

  const hasModelError = publishErrors.some((error) => error.field === 'model_connection_id')

  return (
    <ModelStrategyShell
      title="批量生图"
      description="按风格轮选提示词模板，并根据模板是否配置参考图自动选择生成模式。"
    >
      <section className={`scene-model-field${hasModelError ? ' has-error' : ''}`}>
        <div><span>批量场景应用模型</span><p>只列出已验证图生图能力的连接；该选择不会改变单图编辑场景。</p></div>
        <label><span className="sr-only">选择批量场景应用模型</span><select value={draft.model_connection_id} onChange={(event) => { void persistDraft({ ...draft, model_connection_id: event.target.value }) }}>
          <option value="">请选择已验证连接</option>
          {verifiedConnections.map((connection) => <option value={connection.id} key={connection.id}>{connection.provider} / {connection.model_id} · 已验证</option>)}
        </select></label>
      </section>

      <div className="batch-policy-meta" aria-live="polite">
        <span className={`batch-draft-status ${draftSaveState}`}>
          {draftSaveState === 'saving' ? <><LoaderCircle className="strategy-spin" size={13} />正在保存草稿</> : draftSaveState === 'error' ? '草稿保存失败' : draftSaveState === 'saved' ? '草稿已保存' : '尚无草稿变更'}
        </span>
        {draftSaveState === 'error' && <button type="button" onClick={() => { const currentDraft = draftRef.current; if (currentDraft) void persistDraft(currentDraft) }}>重试</button>}
        <span className="batch-published-time">最新发布策略时间：{formatStrategyTimestamp(lastPublishedAt)}</span>
        {draftUpdatedAt && <span className="sr-only">草稿最近保存于 {formatStrategyTimestamp(draftUpdatedAt)}</span>}
      </div>

      {publishErrors.length > 0 && <div className="strategy-publish-errors" role="alert"><b>本次未发布，仍有 {publishErrors.length} 项需要处理。</b><p>{formatPublishError(publishErrors[0]!)}</p></div>}

      <section className="batch-policy-editor">
          <header className="strategy-section-title batch-editor-title">
            <div><h2>风格与模板</h2><p>{draft.styles.length} 个风格 · 本轮合计生成 {totalGenerationCount} 张图片（最多 9 张）</p></div>
            <div className="batch-editor-actions">
              <button className="internal-button strategy-button-with-icon" type="button" onClick={() => openStyleForm()}><Plus size={15} />新增风格</button>
              <button className="internal-button primary strategy-button-with-icon" type="button" disabled={isPublishing || draftSaveState === 'saving'} onClick={() => void publish()}>{isPublishing ? <LoaderCircle className="strategy-spin" size={16} /> : <Send size={16} />}{isPublishing ? '正在发布...' : '发布策略'}</button>
            </div>
          </header>
          <div className="batch-style-list">
            {draft.styles.map((style, styleIndex) => {
              const completeCount = style.templates.filter(isCompleteBatchTemplate).length
              const styleHasError = publishErrors.some((error) => error.field.startsWith(`styles[${styleIndex}]`))
              const isExpanded = expandedStyleIds.has(style.id)
              const templatesToDisplay = visibleBatchTemplates(style.templates, isExpanded)
              return <article key={style.id} className={`batch-style-row${styleHasError ? ' has-error' : ''}`}>
                <header className="batch-style-head">
                  <div className="batch-style-identity"><span>风格 {String(styleIndex + 1).padStart(2, '0')}</span><b>{style.name.trim() || '未命名风格'}</b><small>{completeCount} / {style.templates.length} 个完整模板</small></div>
                  <label className="batch-count-field"><span>生成数</span><input
                    className="batch-count-input"
                    aria-label={`${style.name || '未命名风格'}生成数`}
                    type="number"
                    min={0}
                    max={9}
                    step={1}
                    inputMode="numeric"
                    value={style.generation_count}
                    title="输入 0 至 9 的整数；所有风格合计最多生成 9 张图片"
                    disabled={completeCount === 0 || draftSaveState === 'saving'}
                    onChange={(event) => {
                      const nextCount = Number(event.target.value)
                      if (Number.isInteger(nextCount)) void updateGenerationCount(style.id, nextCount)
                    }}
                  /></label>
                  <div className="strategy-row-actions">
                    <button className="strategy-icon-button" type="button" title="编辑风格" aria-label={`编辑风格 ${style.name || '未命名'}`} onClick={() => openStyleForm(style)}><Pencil size={16} /></button>
                    <button className="strategy-icon-button danger" type="button" title="删除风格" aria-label={`删除风格 ${style.name || '未命名'}`} onClick={() => deleteStyle(style.id)}><Trash2 size={16} /></button>
                  </div>
                </header>
                {completeCount === 0 && <p className="batch-gate-note">创建至少一个完整模板后，生成数才可编辑；当前已固定为 0。</p>}
                {completeCount > 0 && style.generation_count > completeCount && <p className="batch-rotation-note">生成数大于完整模板数，将按独立游标循环复用模板及其可选参考图。</p>}
                <div className="batch-template-list">
                  {templatesToDisplay.map((template, templateIndex) => {
                    const firstReferenceId = template.reference_images[0]
                    const asset = assets.find((item) => item.id === firstReferenceId)
                    const complete = isCompleteBatchTemplate(template) && template.reference_images.every((id) => assets.some((item) => item.id === id))
                    const previewUrl = firstReferenceId ? previewUrls[firstReferenceId] : undefined
                    return <div className={`batch-template-row${complete ? '' : ' incomplete'}`} key={template.id}>
                      <div className="batch-template-reference">{previewUrl ? <img src={previewUrl} alt={`${template.name || '提示词模板'}参考图`} /> : <span><FileImage size={18} />{asset ? `${template.reference_images.length} 张参考图` : '文生图'}</span>}</div>
                      <div className="batch-template-copy"><div><b>{template.name.trim() || '未命名模板'}</b><span className={complete ? 'complete' : 'incomplete'}>{complete ? '完整' : '待完善'}</span></div><p>{template.positive_prompt.trim() || '未填写正提示词'}</p><small>{template.negative_prompt?.trim() || '负提示词：-'}</small></div>
                      <div className="strategy-row-actions">
                        <button className="strategy-icon-button" type="button" title="编辑模板" aria-label={`编辑模板 ${template.name || templateIndex + 1}`} onClick={() => openTemplateForm(style.id, template)}><Pencil size={16} /></button>
                        <button className="strategy-icon-button danger" type="button" title="删除模板" aria-label={`删除模板 ${template.name || templateIndex + 1}`} onClick={() => deleteTemplate(style.id, template.id)}><Trash2 size={16} /></button>
                      </div>
                    </div>
                  })}
                  <div className="batch-template-footer">
                    {style.templates.length > 3 && <button className="batch-template-toggle" type="button" aria-expanded={isExpanded} onClick={() => toggleStyleTemplates(style.id)}>{isExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}{isExpanded ? '收起模板' : `展开全部 ${style.templates.length} 个`}</button>}
                    <button className="batch-add-template" type="button" onClick={() => openTemplateForm(style.id)}><Plus size={15} />新增提示词模板</button>
                  </div>
                </div>
              </article>
            })}
            {!draft.styles.length && <div className="strategy-empty-state"><Archive size={28} /><b>尚无风格类型</b><span>新增风格后，再配置提示词模板与可选参考图。</span></div>}
          </div>
      </section>

      {styleForm && <StrategyDialog
        title={styleForm.id ? '编辑风格类型' : '新增风格类型'}
        description="完成后即保存到策略草稿；发布前不会影响正在使用的策略。"
        onClose={() => { if (draftSaveState !== 'saving' && !isUploading) closeStyleForm() }}
        footer={<><button className="internal-button" type="button" disabled={draftSaveState === 'saving' || isUploading} onClick={closeStyleForm}>取消</button><button className="internal-button primary" type="button" disabled={draftSaveState === 'saving' || isUploading} onClick={() => void applyStyleForm()}>{isUploading || draftSaveState === 'saving' ? '正在保存...' : '完成'}</button></>}
      ><div className="strategy-form single-column">
        <label><span>风格名称 <b>*</b></span><input autoFocus value={styleForm.name} onChange={(event) => setStyleForm({ ...styleForm, name: event.target.value })} placeholder="如：极简科技" maxLength={32} /></label>
        <div className="style-showcase-editor">
          <span>展示样图 <small>请上传 1～3 张风格类型样图，该图片不参与模型生图</small></span>
          <div className="style-showcase-list">
            {styleForm.showcaseImages.map((image) => <div className="style-showcase-item" key={image.key}>
              {image.previewUrl ? <img src={image.previewUrl} alt={image.filename} /> : <div className="style-showcase-placeholder"><FileImage size={18} /></div>}
              <button className="strategy-icon-button danger" type="button" title="删除展示样图" aria-label="删除展示样图" onClick={() => removeShowcaseImage(image.key)} disabled={isUploading}><X size={14} /></button>
            </div>)}
            {styleForm.showcaseImages.length < 3 && <label className="style-showcase-add" title="上传展示样图"><ImagePlus size={18} /><span>上传</span><input className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" multiple disabled={isUploading} onChange={(event) => { chooseShowcaseImages(Array.from(event.target.files ?? [])); event.currentTarget.value = '' }} /></label>}
          </div>
        </div>
        {modalError && <p className="strategy-form-error">{modalError}</p>}
      </div></StrategyDialog>}

      {templateForm && <StrategyDialog
        wide
        title={templateForm.templateId ? '编辑提示词模板' : '新增提示词模板'}
        description="名称与正提示词必填；负提示词和参考图均可留空。"
        onClose={closeTemplateForm}
        footer={<><button className="internal-button" type="button" disabled={isUploading || isSelectingReferences} onClick={closeTemplateForm}>取消</button><button className="internal-button primary" type="button" disabled={isUploading || isSelectingReferences} onClick={() => void applyTemplateForm()}>{isUploading ? '正在保存...' : isSelectingReferences ? '正在检查图片...' : '保存'}</button></>}
      >
        <div className="template-dialog-layout">
          <div className="template-reference-editor">
            <span>参考图（选填） <em className="template-reference-count">{templateForm.referenceImages.length} / 8</em></span>
            <div className="template-reference-stack" tabIndex={0} aria-label={`已添加 ${templateForm.referenceImages.length} 张参考图`}>
              {templateForm.referenceImages.length ? templateForm.referenceImages.slice(0, 3).map((item, index) => {
                const src = item.previewUrl ?? (item.assetId ? previewUrls[item.assetId] : undefined)
                return <div className={`template-reference-stack-item stack-item-${index}`} key={item.key}>
                  {src ? <img src={src} alt={item.filename} /> : <FileImage size={22} />}
                </div>
              }) : <div className="template-reference-stack-empty"><FileImage size={25} /><span>暂无参考图</span></div>}
              {templateForm.referenceImages.length === 1 && <button type="button" className="template-reference-remove template-reference-stack-remove" title={`删除 ${templateForm.referenceImages[0]!.filename}`} aria-label={`删除 ${templateForm.referenceImages[0]!.filename}`} disabled={isUploading || isSelectingReferences} onClick={() => removeReferenceImage(templateForm.referenceImages[0]!.key)}><X size={16} /></button>}
              {templateForm.referenceImages.length > 1 && <b className="template-reference-stack-badge">+{templateForm.referenceImages.length - 1}</b>}
              {templateForm.referenceImages.length > 1 && <div className={`template-reference-popover count-${Math.min(templateForm.referenceImages.length, 8)}`} role="list" aria-label="参考图列表">
                {templateForm.referenceImages.map((item, index) => {
                  const src = item.previewUrl ?? (item.assetId ? previewUrls[item.assetId] : undefined)
                  return <div className="template-reference-popover-item" role="listitem" key={item.key}>
                    <button type="button" className="template-reference-preview" title={`第 ${index + 1} 张：预览 ${item.filename}`} aria-label={`第 ${index + 1} 张：预览 ${item.filename}`} onClick={() => src && setLightbox({ src, alt: item.filename })}>
                      <span className="template-reference-order" aria-hidden="true">{index + 1}</span>
                      {src ? <img src={src} alt={item.filename} /> : <FileImage size={18} />}
                    </button>
                    <span title={item.filename}>{item.filename}</span>
                    <button type="button" className="template-reference-remove" title={`删除第 ${index + 1} 张 ${item.filename}`} aria-label={`删除第 ${index + 1} 张 ${item.filename}`} disabled={isUploading || isSelectingReferences} onClick={() => removeReferenceImage(item.key)}><X size={14} /></button>
                  </div>
                })}
              </div>}
            </div>
            <label className={`template-upload-button${isUploading || isSelectingReferences ? ' disabled' : ''}`}><ImagePlus size={15} />添加参考图<input className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={isUploading || isSelectingReferences} onChange={(event) => { void chooseReferenceImages(Array.from(event.target.files ?? [])); event.currentTarget.value = '' }} /></label>
            <small className="template-asset-meta">新增或删除先保留在弹窗内，点击保存后写入策略草稿。运行时用户上传图优先，其后按当前参考图顺序发送。</small>
          </div>
          <div className="strategy-form single-column">
            <label><span>模板名称 <b>*</b></span><input value={templateForm.name} onChange={(event) => setTemplateForm({ ...templateForm, name: event.target.value })} placeholder="如：几何秩序" maxLength={48} /></label>
            <label><span>正提示词 <b>*</b></span><textarea value={templateForm.positivePrompt} onChange={(event) => setTemplateForm({ ...templateForm, positivePrompt: event.target.value })} placeholder="必须包含 {{域名}}，可选 {{用户参考要求}}" /><small><code>{'{{域名}}'}</code> 必须出现 1 次；<code>{'{{用户参考要求}}'}</code> 可选，填写时最多出现 1 次。</small></label>
            <label><span>负提示词（选填）</span><textarea value={templateForm.negativePrompt} onChange={(event) => setTemplateForm({ ...templateForm, negativePrompt: event.target.value })} placeholder="如：避免水印、复杂背景、低清晰度" /></label>
            {modalError && <p className="strategy-form-error">{modalError}</p>}
          </div>
        </div>
      </StrategyDialog>}

      {lightbox && <div className="strategy-lightbox" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setLightbox(null) }}><button type="button" className="strategy-lightbox-close" title="关闭预览" aria-label="关闭预览" onClick={() => setLightbox(null)}><X size={18} /></button><img src={lightbox.src} alt={lightbox.alt} /></div>}

    </ModelStrategyShell>
  )
}
