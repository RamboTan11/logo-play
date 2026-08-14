import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { ClientShell } from '../components/ClientShell'
import { AdoptionConfirmDialog } from '../components/AdoptionConfirmDialog'
import { GenerationWaitingState } from '../components/GenerationWaitingState'
import { CachedImage } from '../components/CachedImage'
import { LogoArtwork } from '../components/LogoArtwork'
import { adoptLogo } from '../services/designTasksService'
import { saveLogo } from '../services/savedLogosService'
import { useGenerationStore } from '../stores/useGenerationStore'
import { useToastStore } from '../stores/useToastStore'
import { rememberLastCreationPath } from '../utils/clientNavigation'
import { resultGridRows } from '../utils/generationResultLayout'
import { useClientLanguage } from '../i18n/useClientLanguage'

export function GenerationResultsPage() {
  const { t } = useClientLanguage()
  const navigate = useNavigate()
  const activeBatchId = useGenerationStore((state) => state.activeBatchId ?? null)
  const batchHistory = useGenerationStore((state) => Array.isArray(state.batchHistory) ? state.batchHistory : [])
  const isRegenerating = useGenerationStore((state) => state.isRegenerating === true)
  const isCompletedBatchesRestored = useGenerationStore((state) => state.isCompletedBatchesRestored === true)
  const retryingSlots = useGenerationStore((state) => state.retryingSlots)
  const retrySlot = useGenerationStore((state) => state.retrySlot)
  const regenerate = useGenerationStore((state) => state.regenerate)
  const restoreCompletedBatches = useGenerationStore((state) => state.restoreCompletedBatches)
  const selectBatch = useGenerationStore((state) => state.selectBatch)
  const returnToCreation = useGenerationStore((state) => state.returnToCreation)
  const showToast = useToastStore((state) => state.showToast)
  const visibleBatches = useMemo(() => batchHistory, [batchHistory])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [adoptionSuggestion, setAdoptionSuggestion] = useState('')
  const [pendingAction, setPendingAction] = useState<'save' | 'adopt' | null>(null)
  const [isChangeConfirmOpen, setIsChangeConfirmOpen] = useState(false)
  const batch = visibleBatches.find((item) => item.request_id === activeBatchId) ?? visibleBatches.at(-1) ?? null
  const activeBatchIndex = visibleBatches.findIndex((item) => item.request_id === batch?.request_id)
  const selectedBatch = batch
  const options = useMemo(() => {
    if (!selectedBatch) return []
    if (selectedBatch.candidates.length > 0) {
      return [...selectedBatch.candidates]
        .sort((left, right) => left.slot_index - right.slot_index)
        .map((candidate) => ({
          ...candidate,
          id: candidate.logo_version_id
            ?? `${selectedBatch.request_id}-slot-${candidate.slot_index}`,
          imageUrl: candidate.image_url,
        }))
    }
    return selectedBatch.logo_versions.map((logo, slotIndex) => ({
      slot_index: slotIndex,
      status: 'succeeded' as const,
      logo_version_id: logo.id,
      image_url: logo.image_url,
      failure: null,
      retry_token: null,
      id: logo.id,
      imageUrl: logo.image_url,
    }))
  }, [selectedBatch])

  useEffect(() => {
    rememberLastCreationPath('/results')
    if (typeof restoreCompletedBatches === 'function') restoreCompletedBatches()
  }, [restoreCompletedBatches])

  if (!isCompletedBatchesRestored) {
    return <ClientShell><main className="client-main results-empty" aria-live="polite"><p>{t('正在恢复生成结果...')}</p></main></ClientShell>
  }

  if (!batch) {
    return <ClientShell><main className="client-main results-empty"><p>{t('暂无可查看的生成结果。')}</p><button className="secondary" onClick={() => navigate('/create')}>{t('返回创作')}</button></main></ClientShell>
  }

  const selectedOptionId = options.some((option) => option.id === selectedId) ? selectedId : null

  const save = async (id: string) => {
    if (pendingAction) return
    setPendingAction('save')
    try {
      await saveLogo(id, batch.domain)
      showToast(t('收藏成功，可前往'), { label: t('我的方案'), to: '/my-plans', suffix: t('查看') })
    } catch {
      showToast(t('收藏失败。'))
    } finally {
      setPendingAction(null)
    }
  }
  const adopt = async (suggestion = adoptionSuggestion, confirmReplaceActiveTask = false) => {
    if (!selectedOptionId || pendingAction) return
    setPendingAction('adopt')
    try {
      const result = await adoptLogo(
        selectedOptionId,
        suggestion.trim() || null,
        import.meta.env.VITE_USE_MOCK === 'true'
          ? { domain: batch.domain, initialLogoVersionId: selectedOptionId, aiEditInputs: [] }
          : undefined,
        confirmReplaceActiveTask,
      )
      if (result === 'active_task_confirmation_required') {
        setIsChangeConfirmOpen(true)
        return
      }
      setIsChangeConfirmOpen(false)
      if (result !== 'completed_task_exists' && !confirmReplaceActiveTask) {
        showToast(t('提交成功'))
        navigate('/my-plans')
        return
      }
      showToast(
        result === 'completed_task_exists' ? t('已有完成交付的方案，请前往') : t('采用成功，可前往'),
        { label: t('我的方案'), to: '/my-plans', suffix: t('查看') },
      )
    } catch {
      showToast(t('采用失败。'))
    } finally {
      setPendingAction(null)
    }
  }

  const isFailed = selectedBatch?.status === 'failed'

  return (
    <ClientShell>
      <main className="client-main generation-main">
        <h1 className="sr-only">{t('生成结果')}</h1>
        <section className="generation-workspace">
          <section className="generation-results-panel" aria-live="polite">
            <header className="batch-toolbar">
              <button className="toolbar-icon icon-tooltip toolbar-return" data-tooltip={t('返回创作')} aria-label={t('返回创作')} title={t('返回创作')} onClick={() => { returnToCreation(); navigate('/create') }}>←</button>
              <div className="batch-toolbar-actions" role="toolbar" aria-label={t('生成批次工具')}>
                <button className="toolbar-icon icon-tooltip" data-tooltip={t('上一批')} aria-label={t('上一批')} title={t('上一批')} disabled={isRegenerating || activeBatchIndex <= 0} onClick={() => {
                  const previousBatch = visibleBatches[activeBatchIndex - 1]
                  if (previousBatch) selectBatch(previousBatch.request_id)
                }}>‹</button>
                <button className="toolbar-icon icon-tooltip" data-tooltip={t('下一批')} aria-label={t('下一批')} title={t('下一批')} disabled={isRegenerating || activeBatchIndex < 0 || activeBatchIndex >= visibleBatches.length - 1} onClick={() => {
                  const nextBatch = visibleBatches[activeBatchIndex + 1]
                  if (nextBatch) selectBatch(nextBatch.request_id)
                }}>›</button>
                <button className={`toolbar-icon icon-tooltip ${isRegenerating ? 'loading' : ''}`} data-tooltip={t('换一批')} aria-label={t('换一批')} title={t('换一批')} disabled={isRegenerating} onClick={() => void regenerate()}>↻</button>
              </div>
            </header>
            {isFailed && !isRegenerating ? <div className="generation-loading-panel"><b>{t('本批方案未能完整生成')}</b><span>{t('请稍后重新生成。')}</span></div> : <div className="generation-results-stage" aria-busy={isRegenerating}>
              <section className="results-grid results-workspace-grid" style={{ '--result-rows': resultGridRows(options.length) } as CSSProperties} aria-label={t('Logo 方案列表')}>
                {options.map((option, index) => {
                  const retryKey = `${batch.request_id}:${option.slot_index}`
                  const retrying = retryingSlots.includes(retryKey)
                  if (option.status === 'failed') {
                    return <article className="result-card result-card-failed" key={option.id}>
                      <button
                        className={retrying ? 'result-slot-retry loading' : 'result-slot-retry'}
                        aria-label={`${t('重试失败方案')} ${option.slot_index + 1}`}
                        title={t('重试此方案')}
                        disabled={retrying || !option.retry_token}
                        onClick={() => option.retry_token
                          && void retrySlot(batch.request_id, option.slot_index, option.retry_token)}
                      ><RefreshCw aria-hidden="true" /></button>
                      <span>{t('此方案生成失败，请重试。')}</span>
                    </article>
                  }
                  const selected = selectedOptionId === option.logo_version_id
                  return <article className={'result-card ' + (selected ? 'selected' : '')} key={option.id}>
                    <button className="result-select-control" aria-label={t('选择方案')} disabled={isRegenerating} onClick={() => setSelectedId(option.id)} />
                    <button className="result-edit-icon" aria-label={t('单图编辑')} title={t('单图编辑')} disabled={isRegenerating} onClick={(event) => { event.stopPropagation(); navigate('/edit/' + encodeURIComponent(option.id)) }}>✎</button>
                    {option.imageUrl ? <CachedImage className="generated-logo-image" src={option.imageUrl} alt={t('生成的 Logo')} /> : <LogoArtwork variant={index + (batch.request_id.length % 6)} domain={batch.domain} />}
                  </article>
                })}
              </section>
              {isRegenerating && <div className="generation-waiting-overlay"><GenerationWaitingState title={t('正在生成新一批方案')} description={t('正在探索新的设计方向，生成结果会自动显示')} /></div>}
            </div>}
          </section>
          <aside className="decision-panel" aria-live="polite">
            <h2>{t('选择初稿')}</h2>
            <p className="draft-adoption-note">{t('采用后由我们继续优化为最终成品')}</p>
            <label className="adoption-note-field"><span>{t('优化要求（选填）')}</span><textarea placeholder={t('可输入优化要求，默认优化为行业品牌特色的立体效果。')} value={adoptionSuggestion} disabled={!selectedOptionId || isRegenerating} onChange={(event) => setAdoptionSuggestion(event.target.value)} /></label>
            <div className="decision-actions confirm-actions"><button className="secondary" disabled={!selectedOptionId || isRegenerating || pendingAction !== null} onClick={() => selectedOptionId && void save(selectedOptionId)}>{t(pendingAction === 'save' ? '收藏中...' : '收藏')}</button><div className="adopt-tooltip"><button className="primary" aria-label={t('采用初稿')} title={t('采用后将进入成品优化，并由我们完成最终交付')} disabled={!selectedOptionId || isRegenerating || pendingAction !== null} onClick={() => void adopt()}>{t(pendingAction === 'adopt' ? '提交中...' : '采用')}</button><span>{t('采用后将进入成品优化，并由我们完成最终交付')}</span></div></div>
          </aside>
        </section>
        {isChangeConfirmOpen && selectedOptionId && <AdoptionConfirmDialog domain={batch.domain} initialSuggestion={adoptionSuggestion} isChange isSubmitting={pendingAction === 'adopt'} onClose={() => setIsChangeConfirmOpen(false)} onConfirm={(suggestion) => void adopt(suggestion, true)} />}
      </main>
    </ClientShell>
  )
}
