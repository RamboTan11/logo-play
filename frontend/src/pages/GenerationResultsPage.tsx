import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, LoaderCircle, RefreshCw, Star } from 'lucide-react'
import { ClientShell } from '../components/ClientShell'
import { AdoptionConfirmDialog } from '../components/AdoptionConfirmDialog'
import { BatchReplaceConfirmDialog } from '../components/BatchReplaceConfirmDialog'
import { ResultEditDialog } from '../components/ResultEditDialog'
import type { ResultEditVersion } from '../components/ResultEditDialog'
import { CachedImage, preloadCachedImage, preloadImage } from '../components/CachedImage'
import { LogoArtwork } from '../components/LogoArtwork'
import { adoptLogo } from '../services/designTasksService'
import { createSingleEditGeneration, getSingleEditContext, getSingleEditStatus } from '../services/generationsService'
import { getSavedLogos, saveLogo } from '../services/savedLogosService'
import { useGenerationStore } from '../stores/useGenerationStore'
import { useToastStore } from '../stores/useToastStore'
import { rememberLastCreationPath } from '../utils/clientNavigation'
import { resultGridRows } from '../utils/generationResultLayout'
import { useClientLanguage } from '../i18n/useClientLanguage'
import type { GenerationBatch } from '../types/api'

type CandidateOverride = { logoVersionId: string; imageUrl: string | null }
type RememberedResultSelection = { batchId: string; logoVersionId: string }

const defaultEditInstruction = '重新生成当前相似风格的 logo 图。'
const candidateOverrideStorageKey = 'logo-generated.result-candidate-overrides'
const iphoneMockupReferenceUrl = `${import.meta.env.BASE_URL}mockups/iphone-home-screen.webp`
let rememberedResultSelection: RememberedResultSelection | null = null

function readCandidateOverrides(): Record<string, CandidateOverride> {
  if (typeof window === 'undefined') return {}
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(candidateOverrideStorageKey) ?? '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return Object.fromEntries(Object.entries(parsed).filter(([, value]) => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return false
      const record = value as Record<string, unknown>
      return typeof record.logoVersionId === 'string'
        && (record.imageUrl === null || typeof record.imageUrl === 'string')
    })) as Record<string, CandidateOverride>
  } catch {
    window.localStorage.removeItem(candidateOverrideStorageKey)
    return {}
  }
}

function writeCandidateOverrides(overrides: Record<string, CandidateOverride>): void {
  if (typeof window !== 'undefined') window.localStorage.setItem(candidateOverrideStorageKey, JSON.stringify(overrides))
}

type ResultOption = GenerationBatch['candidates'][number] & {
  id: string
  logoVersionId: string | null
  imageUrl: string | null
  overrideKey: string
}

function optionsForBatch(batch: GenerationBatch, candidateOverrides: Record<string, CandidateOverride>): ResultOption[] {
  const source = batch.candidates.length > 0
    ? [...batch.candidates].sort((left, right) => left.slot_index - right.slot_index)
    : batch.logo_versions.map((logo, slotIndex) => ({
      slot_index: slotIndex,
      status: 'succeeded' as const,
      logo_version_id: logo.id,
      image_url: logo.image_url,
      failure: null,
      retry_token: null,
    }))
  return source.map((candidate) => {
    const key = `${batch.request_id}:${candidate.slot_index}`
    const override = candidate.status === 'succeeded' ? candidateOverrides[key] : undefined
    const logoVersionId = override?.logoVersionId ?? candidate.logo_version_id
    return {
      ...candidate,
      id: logoVersionId ?? `${key}:failed`,
      logoVersionId,
      imageUrl: override?.imageUrl ?? candidate.image_url,
      overrideKey: key,
    }
  })
}

export function GenerationResultsPage() {
  const { t } = useClientLanguage()
  const navigate = useNavigate()
  const activeBatchId = useGenerationStore((state) => state.activeBatchId ?? null)
  const batchHistory = useGenerationStore((state) => Array.isArray(state.batchHistory) ? state.batchHistory : [])
  const isRegenerating = useGenerationStore((state) => state.isRegenerating === true)
  const activeTargetCount = useGenerationStore((state) => state.activeTargetCount)
  const isCompletedBatchesRestored = useGenerationStore((state) => state.isCompletedBatchesRestored === true)
  const retryingSlots = useGenerationStore((state) => state.retryingSlots)
  const retrySlot = useGenerationStore((state) => state.retrySlot)
  const regenerate = useGenerationStore((state) => state.regenerate)
  const restoreCompletedBatches = useGenerationStore((state) => state.restoreCompletedBatches)
  const selectBatch = useGenerationStore((state) => state.selectBatch)
  const returnToCreation = useGenerationStore((state) => state.returnToCreation)
  const showToast = useToastStore((state) => state.showToast)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [candidateOverrides, setCandidateOverrides] = useState<Record<string, CandidateOverride>>(readCandidateOverrides)
  const [savedIds, setSavedIds] = useState<Set<string>>(() => new Set())
  const [pendingAction, setPendingAction] = useState<'save' | 'adopt' | 'edit' | null>(null)
  const adoptionSuggestion = ''
  const [adoptionError, setAdoptionError] = useState<string | null>(null)
  const [adoptionDialogMode, setAdoptionDialogMode] = useState<'initial' | 'replace' | null>(null)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [isReplaceConfirmOpen, setIsReplaceConfirmOpen] = useState(false)
  const historyScrollRef = useRef<HTMLDivElement>(null)
  const visibleBatches = useMemo(() => batchHistory, [batchHistory])
  const newestBatchId = visibleBatches.at(-1)?.request_id ?? null
  const batch = visibleBatches.find((item) => item.request_id === activeBatchId) ?? visibleBatches.at(-1) ?? null

  const optionsByBatch = useMemo(() => visibleBatches.map((item) => ({
    batch: item,
    options: optionsForBatch(item, candidateOverrides),
  })), [candidateOverrides, visibleBatches])
  const selectedOption = optionsByBatch
    .flatMap((entry) => entry.options)
    .find((option) => option.id === selectedId && option.status === 'succeeded') ?? null
  const selectedOptionId = selectedOption?.logoVersionId ?? null
  const selectedBatch = selectedOption
    ? visibleBatches.find((item) => item.request_id === selectedOption.overrideKey.split(':')[0]) ?? batch
    : null
  const selectedDomain = selectedBatch?.domain ?? batch?.domain ?? ''

  useEffect(() => {
    rememberLastCreationPath('/results')
    if (typeof restoreCompletedBatches === 'function') restoreCompletedBatches()
  }, [restoreCompletedBatches])

  useEffect(() => {
    let active = true
    void getSavedLogos().then((items) => {
      if (active) setSavedIds(new Set(items.map((item) => item.logo_version_id)))
    }).catch(() => undefined)
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!batch) {
      setSelectedId(null)
      return
    }
    if (!selectedId && rememberedResultSelection?.batchId === batch.request_id) {
      setSelectedId(rememberedResultSelection.logoVersionId)
    }
  }, [batch, selectedId])

  useEffect(() => {
    preloadImage(iphoneMockupReferenceUrl)
  }, [])

  useEffect(() => {
    // Keep the selected logo warm before a regeneration can replace the
    // history payload. This prevents the mockup from flashing a broken image
    // while the new batch is being polled.
    if (selectedOption?.imageUrl) {
      preloadCachedImage(selectedOption.imageUrl, { thumbnail: true, progressive: true })
    }
  }, [selectedOption?.imageUrl])

  useLayoutEffect(() => {
    const container = historyScrollRef.current
    if (!container) return
    container.scrollTop = container.scrollHeight
  }, [isRegenerating, visibleBatches.length])

  const toggleSaved = async (logoVersionId: string, domain: string) => {
    if (pendingAction || isRegenerating) return
    // The production API creates a saved design but intentionally has no
    // delete endpoint. Do not present a local-only "unsave" state.
    if (savedIds.has(logoVersionId)) return
    setPendingAction('save')
    try {
      await saveLogo(logoVersionId, domain)
      setSavedIds((current) => new Set(current).add(logoVersionId))
      showToast(t('收藏成功，可前往'), { label: t('我的方案'), to: '/my-plans', suffix: t('查看') })
    } catch {
      showToast(t('收藏失败。'))
    } finally {
      setPendingAction(null)
    }
  }

  const adopt = async (suggestion = adoptionSuggestion, confirmReplaceActiveTask = false) => {
    if (!selectedOptionId || !selectedDomain || pendingAction) return
    setPendingAction('adopt')
    setAdoptionError(null)
    try {
      const result = await adoptLogo(
        selectedOptionId,
        suggestion.trim() || null,
        import.meta.env.VITE_USE_MOCK === 'true'
          ? { domain: selectedDomain, initialLogoVersionId: selectedOptionId, aiEditInputs: [] }
          : undefined,
        confirmReplaceActiveTask,
      )
      if (result === 'active_task_confirmation_required') {
        setAdoptionDialogMode('replace')
        return
      }
      setAdoptionDialogMode(null)
      if (result !== 'completed_task_exists' && !confirmReplaceActiveTask) {
        showToast(t('提交成功'))
        navigate('/my-plans')
        return
      }
      showToast(
        result === 'completed_task_exists' ? t('已有完成交付的方案，请前往') : t('采用成功，可前往'),
        { label: t('我的方案'), to: '/my-plans', suffix: t('查看') },
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : t('采用失败。')
      setAdoptionError(message)
      showToast(t('采用失败。'))
    } finally {
      setPendingAction(null)
    }
  }

  const generateEdit = async (instruction: string): Promise<ResultEditVersion | null> => {
    if (!selectedOptionId) return null
    setPendingAction('edit')
    try {
      let sourceVersionId = selectedOptionId
      if (import.meta.env.VITE_USE_MOCK !== 'true') {
        const context = await getSingleEditContext(selectedOptionId)
        sourceVersionId = context.current_version_id
        if (sourceVersionId !== selectedOptionId) {
          const current = context.versions.find((version) => version.id === sourceVersionId)
          if (current) {
            setCandidateOverrides((existing) => {
              const next = { ...existing, [selectedOption!.overrideKey]: { logoVersionId: current.id, imageUrl: current.image_url } }
              writeCandidateOverrides(next)
              return next
            })
            setSelectedId(sourceVersionId)
          }
        }
      }
      const accepted = await createSingleEditGeneration(
        sourceVersionId,
        instruction.trim() || defaultEditInstruction,
      )
      if (import.meta.env.VITE_USE_MOCK === 'true') return { id: accepted.request_id, imageUrl: null }
      for (;;) {
        const status = await getSingleEditStatus(accepted.request_id)
        if (status.status === 'processing') {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 600))
          continue
        }
        if (status.status !== 'succeeded') throw new Error(t('新版本生成失败，请稍后重试。'))
        const current = status.versions.find((version) => version.id === status.current_version_id)
        return current ? { id: current.id, imageUrl: current.image_url } : null
      }
    } finally {
      setPendingAction(null)
    }
  }

  const useEditedVersion = (version: ResultEditVersion) => {
    if (!selectedOption) return
    setCandidateOverrides((current) => {
      const next = {
        ...current,
        [selectedOption.overrideKey]: { logoVersionId: version.id, imageUrl: version.imageUrl },
      }
      writeCandidateOverrides(next)
      return next
    })
    setSelectedId(version.id)
    rememberedResultSelection = { batchId: selectedBatch?.request_id ?? batch!.request_id, logoVersionId: version.id }
    setIsEditOpen(false)
  }

  const replaceBatch = async (preserveSelection = false) => {
    const previousSelection = selectedId
    const previousRememberedSelection = rememberedResultSelection
    setIsReplaceConfirmOpen(false)
    if (!preserveSelection) {
      setSelectedId(null)
      rememberedResultSelection = null
    }
    await regenerate()
    if (useGenerationStore.getState().error) {
      setSelectedId(previousSelection)
      rememberedResultSelection = previousRememberedSelection
    }
  }

  if (!isCompletedBatchesRestored) {
    return <ClientShell><main className="client-main results-empty" aria-live="polite"><p>{t('正在恢复生成结果...')}</p></main></ClientShell>
  }
  if (!batch) {
    return <ClientShell><main className="client-main results-empty"><p>{t('暂无可查看的生成结果。')}</p><button className="secondary" onClick={() => navigate('/create')}>{t('返回创作')}</button></main></ClientShell>
  }

  const isFailed = batch.status === 'failed'
  const isBusy = pendingAction !== null
  const replaceBusy = isRegenerating || pendingAction !== null
  const replaceDisabled = pendingAction !== null && !isRegenerating
  const handleReplaceClick = () => {
    if (isRegenerating) {
      showToast(t('正在执行生图任务，请稍后。'))
      return
    }
    if (pendingAction) return
    requestReplaceBatch()
  }
  const requestReplaceBatch = () => {
    if (selectedOptionId) setIsReplaceConfirmOpen(true)
    else void replaceBatch()
  }
  return <ClientShell>
    <main className="client-main generation-main">
      <h1 className="sr-only">{t('生成结果')}</h1>
      <section className="generation-workspace">
        <section className="generation-results-panel" aria-live="polite">
          <header className="batch-toolbar">
            <button className="toolbar-icon icon-tooltip toolbar-return" data-tooltip={t('返回创作')} aria-label={t('返回创作')} title={t('返回创作')} onClick={() => { if (!isRegenerating) returnToCreation(); navigate('/create') }}>←</button>
          </header>
          {isFailed && !isRegenerating ? <div className="generation-loading-panel"><b>{t('本批方案未能完整生成')}</b><span>{t('请稍后重新生成。')}</span></div> : <div className="generation-results-stage" aria-busy={isRegenerating}>
            <div
              className="batch-history-scroll"
              ref={historyScrollRef}
              onScroll={(event) => {
                const container = event.currentTarget
                const center = container.scrollTop + container.clientHeight / 2
                const containerTop = container.getBoundingClientRect().top
                let closest: { id: string; distance: number } | null = null
                for (const section of container.querySelectorAll<HTMLElement>('[data-batch-id]')) {
                  const sectionTop = section.getBoundingClientRect().top - containerTop + container.scrollTop
                  const sectionCenter = sectionTop + section.offsetHeight / 2
                  const candidate = { id: section.dataset.batchId ?? '', distance: Math.abs(sectionCenter - center) }
                  if (candidate.id && (!closest || candidate.distance < closest.distance)) closest = candidate
                }
                if (closest && closest.id !== activeBatchId) selectBatch(closest.id)
              }}
            >
              {optionsByBatch.map(({ batch: historyBatch, options: historyOptions }) => <section key={historyBatch.request_id} data-batch-id={historyBatch.request_id} className="batch-history-section" aria-label={t('Logo 方案列表')}>
                <div className="results-grid results-workspace-grid batch-history-frame" style={{ '--result-rows': resultGridRows(historyOptions.length) } as CSSProperties}>
                  {historyOptions.map((option, index) => {
                    const retryKey = `${historyBatch.request_id}:${option.slot_index}`
                    const retrying = retryingSlots.includes(retryKey)
                    if (option.status === 'failed') return <article className="result-card result-card-failed" key={option.id}>
                      <button className={retrying ? 'result-slot-retry loading' : 'result-slot-retry'} aria-label={`${t('重试失败方案')} ${option.slot_index + 1}`} title={t('重试此方案')} disabled={retrying || !option.retry_token || isBusy} onClick={() => option.retry_token && void retrySlot(historyBatch.request_id, option.slot_index, option.retry_token)}><RefreshCw aria-hidden="true" /></button>
                      <span>{t('此方案生成失败，请重试。')}</span>
                    </article>
                    const selected = selectedOption?.id === option.id
                    const saved = option.logoVersionId ? savedIds.has(option.logoVersionId) : false
                    const isNewestBatch = historyBatch.request_id === newestBatchId
                    return <article className={`result-card ${selected ? 'selected' : ''}`} key={option.id}>
                      <button className="result-select-control" aria-label={selected ? t('取消选择方案') : t('选择方案')} aria-pressed={selected} disabled={isBusy} onClick={() => {
                        const nextSelection = selected ? null : option.id
                        setSelectedId(nextSelection)
                        rememberedResultSelection = nextSelection
                          ? { batchId: historyBatch.request_id, logoVersionId: nextSelection }
                          : null
                      }} />
                      <button className={`result-save-icon ${saved ? 'saved' : ''}`} aria-label={saved ? t('已收藏') : t('收藏方案')} aria-pressed={saved} title={saved ? t('已收藏') : t('收藏方案')} disabled={isBusy || !option.logoVersionId || saved} onClick={(event) => { event.stopPropagation(); if (option.logoVersionId) void toggleSaved(option.logoVersionId, historyBatch.domain) }}><Star aria-hidden="true" fill={saved ? 'currentColor' : 'none'} /></button>
                      {option.imageUrl ? <CachedImage className="generated-logo-image" src={option.imageUrl} alt={t('生成的 Logo')} thumbnail loading={isNewestBatch ? 'eager' : 'lazy'} fetchPriority={isNewestBatch ? 'high' : 'low'} /> : <LogoArtwork variant={index + (historyBatch.request_id.length % 6)} domain={historyBatch.domain} />}
                    </article>
                  })}
                </div>
              </section>)}
              {isRegenerating && <section className="batch-history-section batch-history-generating" aria-label={t('正在生成新一批方案')}>
                <div className="results-grid results-workspace-grid batch-history-frame" style={{ '--result-rows': resultGridRows(Math.max(activeTargetCount ?? batch.target_count, 1)) } as CSSProperties}>
                  {Array.from({ length: Math.max(activeTargetCount ?? batch.target_count, 1) }, (_, index) => <article className="result-card result-card-generating" key={`generating-${index}`} aria-label={`${t('正在生成新一批方案')} ${index + 1}`}>
                    <LoaderCircle aria-hidden="true" />
                  </article>)}
                </div>
                <p className="batch-generating-hint">{t('预计需要 1～3 分钟，请稍等。')}</p>
              </section>}
            </div>
          </div>}
        </section>
        <aside className="decision-panel result-workspace-panel" aria-live="polite">
          {!selectedOption ? <>
            <h2 className="result-workspace-title">{t('点击预览样机效果并选择提交您喜欢的风格')}</h2><p className="result-workspace-guide">{t('若没有您喜欢的，可以点击下方按钮换一批')}</p>
            <button className="secondary result-regenerate-button" type="button" disabled={replaceDisabled} aria-disabled={replaceBusy} onClick={handleReplaceClick}><RefreshCw aria-hidden="true" />{t('换一批')}</button>
            <p className="result-domain-hint">{t('若您需修改创作的域名文字，可点击')}<button className="result-domain-back" type="button" aria-label={t('返回创作')} title={t('返回创作')} onClick={() => { if (!isRegenerating) returnToCreation(); navigate('/create') }}><ArrowLeft size={16} aria-hidden="true" /></button>{t('返回创作页进行修改')}</p>
          </> : <>
            <h2>{t('应用样机预览')}</h2>
            <div className="ios-phone-mockup" aria-label={t('应用样机预览')}>
              <img className="ios-phone-reference" src={iphoneMockupReferenceUrl} alt="" aria-hidden="true" loading="eager" decoding="async" />
              <div className="ios-phone-selected-app">
                <div className="ios-phone-selected-icon">{selectedOption.imageUrl ? <CachedImage src={selectedOption.imageUrl} alt={t('生成的 Logo')} thumbnail progressive loading="eager" /> : <LogoArtwork variant={selectedOption.slot_index} domain={selectedDomain} compact />}</div>
                <span>{selectedDomain.split('.')[0].toUpperCase()}</span>
              </div>
            </div>
            <div className="decision-actions result-primary-actions"><button className="secondary" type="button" disabled={isBusy || isRegenerating} onClick={() => setIsEditOpen(true)}>{t('编辑优化')}</button><button className="primary" type="button" disabled={isBusy || isRegenerating} onClick={() => setAdoptionDialogMode('initial')}>{t(pendingAction === 'adopt' ? '提交中...' : '提交采用')}</button></div>
            <button className="result-replace-link" type="button" disabled={replaceDisabled} aria-disabled={replaceBusy} onClick={() => { if (isRegenerating) { showToast(t('正在执行生图任务，请稍后。')); return } void replaceBatch(true) }}>{t('这批您都不喜欢？换一批')}</button>
          </>}
        </aside>
      </section>
      {isEditOpen && selectedOption && selectedOptionId && <ResultEditDialog domain={selectedDomain} source={{ id: selectedOptionId, imageUrl: selectedOption.imageUrl }} variant={selectedOption.slot_index} isPageBusy={isBusy} onClose={() => setIsEditOpen(false)} onGenerate={generateEdit} onUse={useEditedVersion} />}
      {isReplaceConfirmOpen && <BatchReplaceConfirmDialog onClose={() => setIsReplaceConfirmOpen(false)} onConfirm={() => void replaceBatch()} />}
      {adoptionDialogMode && selectedOptionId && <AdoptionConfirmDialog domain={selectedDomain} initialSuggestion={adoptionSuggestion} isChange={adoptionDialogMode === 'replace'} isSubmitting={pendingAction === 'adopt'} errorMessage={adoptionError} onClose={() => { setAdoptionDialogMode(null); setAdoptionError(null) }} onConfirm={(suggestion) => void adopt(suggestion, adoptionDialogMode === 'replace')} />}
    </main>
  </ClientShell>
}
