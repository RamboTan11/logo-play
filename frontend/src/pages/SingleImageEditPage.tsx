import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ClientShell } from '../components/ClientShell'
import { AdoptionConfirmDialog } from '../components/AdoptionConfirmDialog'
import { GenerationWaitingState } from '../components/GenerationWaitingState'
import { CachedImage } from '../components/CachedImage'
import { LogoArtwork } from '../components/LogoArtwork'
import { adoptLogo } from '../services/designTasksService'
import {
  createSingleEditGeneration,
  getSingleEditContext,
  getSingleEditStatus,
} from '../services/generationsService'
import { saveLogo } from '../services/savedLogosService'
import { useGenerationStore } from '../stores/useGenerationStore'
import { useToastStore } from '../stores/useToastStore'
import { rememberLastCreationPath } from '../utils/clientNavigation'
import { createSingleFlightGate } from '../utils/singleFlight'
import { useClientLanguage } from '../i18n/useClientLanguage'

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'
const activeSingleEditStorageKey = 'logo-generated.active-single-edit'

interface Version {
  id: string
  number: number
  editInstruction: string | null
  imageUrl: string | null
}

interface ActiveSingleEditRequest {
  requestId: string
  rootVersionId: string
  sourceVersionId: string
}

function readActiveRequest(): ActiveSingleEditRequest | null {
  if (typeof window === 'undefined') return null
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(activeSingleEditStorageKey) ?? 'null')
    if (
      typeof value === 'object'
      && value !== null
      && 'request_id' in value
      && 'root_version_id' in value
      && 'source_version_id' in value
      && typeof value.request_id === 'string'
      && typeof value.root_version_id === 'string'
      && typeof value.source_version_id === 'string'
    ) {
      return {
        requestId: value.request_id,
        rootVersionId: value.root_version_id,
        sourceVersionId: value.source_version_id,
      }
    }
    window.localStorage.removeItem(activeSingleEditStorageKey)
    return null
  } catch {
    window.localStorage.removeItem(activeSingleEditStorageKey)
    return null
  }
}

function writeActiveRequest(activeRequest: ActiveSingleEditRequest): void {
  window.localStorage.setItem(activeSingleEditStorageKey, JSON.stringify({
    request_id: activeRequest.requestId,
    root_version_id: activeRequest.rootVersionId,
    source_version_id: activeRequest.sourceVersionId,
  }))
}

function clearActiveRequest(): void {
  window.localStorage.removeItem(activeSingleEditStorageKey)
}

export function SingleImageEditPage() {
  const { t } = useClientLanguage()
  const { versionId = '' } = useParams()
  const navigate = useNavigate()
  const mockDomain = useGenerationStore((state) => state.completedGeneration?.domain ?? 'LOGO')
  const [domain, setDomain] = useState(mockDomain)
  const [editInstruction, setEditInstruction] = useState('')
  const [versions, setVersions] = useState<Version[]>(
    isMockMode ? [{ id: versionId, number: 1, editInstruction: null, imageUrl: null }] : [],
  )
  const [rootVersionId, setRootVersionId] = useState<string | null>(null)
  const [activeId, setActiveId] = useState(versionId)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isLoading, setIsLoading] = useState(!isMockMode)
  const [adoptionSuggestion, setAdoptionSuggestion] = useState('')
  const [pendingAction, setPendingAction] = useState<'save' | 'adopt' | null>(null)
  const [isChangeConfirmOpen, setIsChangeConfirmOpen] = useState(false)
  const editChainTokenRef = useRef(0)
  const generationGateRef = useRef(createSingleFlightGate())
  const showToast = useToastStore((state) => state.showToast)
  const visibleVersions = useMemo(
    () => isMockMode ? versions.slice(-2) : versions,
    [versions],
  )
  const activeVersion = visibleVersions.find((version) => version.id === activeId)
    ?? visibleVersions.at(-1)
    ?? null
  const activeVersionId = activeVersion?.id
  const currentIndex = activeVersion
    ? visibleVersions.findIndex((version) => version.id === activeVersion.id)
    : -1

  useEffect(() => {
    if (activeVersionId) rememberLastCreationPath(`/edit/${encodeURIComponent(activeVersionId)}`)
  }, [activeVersionId])

  const applyVersions = (
    nextRootVersionId: string,
    nextDomain: string,
    currentVersionId: string,
    nextVersions: Array<{
      id: string
      version_number: number
      edit_instruction: string | null
      image_url: string
    }>,
  ) => {
    setRootVersionId(nextRootVersionId)
    setDomain(nextDomain)
    setVersions(nextVersions.map((version) => ({
      id: version.id,
      number: version.version_number,
      editInstruction: version.edit_instruction,
      imageUrl: version.image_url,
    })))
    setActiveId(currentVersionId)
  }

  const pollRealRequest = async (
    activeRequest: ActiveSingleEditRequest,
    chainToken: number,
    showSuccess = true,
  ): Promise<void> => {
    if (chainToken !== editChainTokenRef.current) return
    try {
      const status = await getSingleEditStatus(activeRequest.requestId)
      if (
        chainToken !== editChainTokenRef.current
        || status.root_version_id !== activeRequest.rootVersionId
        || status.source_version_id !== activeRequest.sourceVersionId
      ) return
      applyVersions(status.root_version_id, status.domain, status.current_version_id, status.versions)
      if (status.status === 'processing') {
        setIsGenerating(true)
        window.setTimeout(() => void pollRealRequest(activeRequest, chainToken, showSuccess), 600)
        return
      }
      clearActiveRequest()
      setIsGenerating(false)
      if (status.status === 'succeeded') {
        setEditInstruction('')
        if (showSuccess) showToast(t('已生成新版本'))
      } else {
        showToast(t('新版本生成失败，请稍后重试。'))
      }
    } catch {
      if (chainToken !== editChainTokenRef.current) return
      clearActiveRequest()
      setIsGenerating(false)
      showToast(t('新版本状态查询失败。'))
    }
  }

  useEffect(() => {
    if (isMockMode || !versionId) return
    let cancelled = false
    const chainToken = editChainTokenRef.current + 1
    editChainTokenRef.current = chainToken
    const restore = async () => {
      try {
        const context = await getSingleEditContext(versionId)
        if (cancelled) return
        applyVersions(
          context.root_version_id,
          context.domain,
          context.current_version_id,
          context.versions,
        )
        const activeRequest = readActiveRequest()
        if (
          activeRequest
          && activeRequest.rootVersionId === context.root_version_id
          && activeRequest.sourceVersionId === context.current_version_id
        ) {
          await pollRealRequest(activeRequest, chainToken, false)
        }
      } catch {
        if (!cancelled) showToast(t('单图编辑内容加载失败。'))
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void restore()
    return () => {
      cancelled = true
      if (editChainTokenRef.current === chainToken) editChainTokenRef.current += 1
    }
    // The URL identifies the edit chain. Polling owns subsequent server state refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId])

  const generate = async () => {
    if (!activeVersion || isGenerating || !generationGateRef.current.tryEnter()) return
    setIsGenerating(true)
    try {
      const instruction = editInstruction.trim()
      if (!instruction) {
        showToast(t('请填写修改指令。'))
        setIsGenerating(false)
        return
      }
      const response = await createSingleEditGeneration(activeVersion.id, instruction)
      if (isMockMode) {
        const next: Version = {
          id: response.request_id,
          number: versions.length + 1,
          editInstruction: instruction,
          imageUrl: null,
        }
        setVersions((items) => [...items, next])
        setActiveId(next.id)
        setEditInstruction('')
        setIsGenerating(false)
        return
      }
      if (!rootVersionId) {
        setIsGenerating(false)
        showToast(t('单图编辑内容加载失败。'))
        return
      }
      const activeRequest = {
        requestId: response.request_id,
        rootVersionId,
        sourceVersionId: response.source_version_id,
      }
      writeActiveRequest(activeRequest)
      await pollRealRequest(activeRequest, editChainTokenRef.current)
    } catch (error) {
      setIsGenerating(false)
      showToast(t('生成新版本失败，请稍后重试。'))
    } finally {
      generationGateRef.current.leave()
    }
  }

  const save = async () => {
    if (!activeVersion || pendingAction) return
    setPendingAction('save')
    try {
      await saveLogo(activeVersion.id, domain)
      showToast(t('收藏成功，可前往'), { label: t('我的方案'), to: '/my-plans', suffix: t('查看') })
    } catch {
      showToast(t('收藏失败。'))
    } finally {
      setPendingAction(null)
    }
  }

  const adopt = async (suggestion = adoptionSuggestion, confirmReplaceActiveTask = false) => {
    if (!activeVersion || versions.length === 0 || pendingAction) return
    setPendingAction('adopt')
    try {
      const result = await adoptLogo(
        activeVersion.id,
        suggestion.trim() || null,
        isMockMode
          ? { domain, initialLogoVersionId: versions[0].id, aiEditInputs: versions.slice(1).map((version) => version.editInstruction ?? '') }
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

  if (isLoading || !activeVersion) {
    return <ClientShell><main className="client-main results-empty" aria-live="polite"><p>{t('正在加载当前版本...')}</p></main></ClientShell>
  }

  return (
    <ClientShell>
      <main className="client-main single-editor-main">
        <header className="single-editor-head"><div className="single-editor-head-actions" role="toolbar" aria-label={t('单图编辑工具')}><button className="editor-icon-button" aria-label={t('返回生成结果')} title={t('返回生成结果')} onClick={() => navigate('/results')}>←</button><div className="single-editor-tool-group"><button className="editor-icon-button" aria-label={t('上一版本')} title={t('上一版本')} disabled={isGenerating || currentIndex <= 0} onClick={() => setActiveId(visibleVersions[currentIndex - 1].id)}>‹</button><button className="editor-icon-button" aria-label={t('下一版本')} title={t('下一版本')} disabled={isGenerating || currentIndex >= visibleVersions.length - 1} onClick={() => setActiveId(visibleVersions[currentIndex + 1].id)}>›</button></div></div></header>
        <section className="single-editor-workspace">
          <aside className="single-editor-controls"><div className="single-editor-controls-head"><h2>{t('生成修改版本')}</h2><p>{t('只修改指令中明确点名的部分。')}</p></div><label className="refine-prompt-field"><textarea aria-label={t('修改指令')} value={editInstruction} disabled={isGenerating} placeholder={t('例如：仅将图标改为金色，文字、构图和其他颜色保持不变')} onChange={(event) => setEditInstruction(event.target.value)} /></label><button className="primary" disabled={isGenerating || !editInstruction.trim()} onClick={() => void generate()}>{isGenerating ? <span className="loading-copy">{t('正在生成修改版本')}<span className="loading-ellipsis" aria-hidden="true" /></span> : t('生成修改版本')}</button></aside>
          <section className={'single-editor-canvas' + (isGenerating ? ' is-generating' : '')} aria-busy={isGenerating}><div className="single-editor-canvas-meta"><span>{isGenerating ? t('修改版本生成中') : t('当前版本') + ' V' + activeVersion.number}</span><span>{isGenerating ? t('完成后自动呈现') : activeVersion.editInstruction || t('初始生成')}</span></div><div className={'single-editor-stage' + (isGenerating ? ' is-generating' : '')}>{activeVersion.imageUrl ? <CachedImage className="generated-logo-image" src={activeVersion.imageUrl} alt={t('当前 Logo 版本')} loading="eager" /> : <LogoArtwork variant={activeVersion.number - 1} domain={domain} />}{isGenerating && <div className="single-editor-waiting-overlay"><GenerationWaitingState title={t('正在生成修改版本')} description={t('正在按修改指令完成调整，生成结果会自动显示')} /></div>}</div><div className="single-editor-version-note"><b>{isGenerating ? t('当前版本已安全保留') : activeVersion.editInstruction || t('保持当前方向')}</b><span>{isGenerating ? t('生成完成后会自动切换到新版本') : t('仅显示当前版本与紧邻上一版本')}</span></div></section>
          <aside className="decision-panel compact-decision"><span className="decision-zone-kicker">{t('当前版本操作')}</span><div className="decision-selection"><b>V{activeVersion.number}</b><span>{activeVersion.editInstruction || t('初始生成')}</span></div><label className="adoption-note-field"><span>{t('优化要求（选填）')}</span><textarea placeholder={t('可输入优化要求，默认优化为行业品牌特色的立体效果。')} value={adoptionSuggestion} disabled={isGenerating} onChange={(event) => setAdoptionSuggestion(event.target.value)} /></label><div className="decision-actions confirm-actions"><button className="secondary" disabled={isGenerating || pendingAction !== null} onClick={() => void save()}>{t(pendingAction === 'save' ? '收藏中...' : '收藏')}</button><div className="adopt-tooltip"><button className="primary" disabled={isGenerating || pendingAction !== null} onClick={() => void adopt()}>{t(pendingAction === 'adopt' ? '提交中...' : '采用')}</button><span>{t('采用后将进入成品优化，并由我们完成最终交付')}</span></div></div></aside>
        </section>
        {isChangeConfirmOpen && <AdoptionConfirmDialog domain={domain} initialSuggestion={adoptionSuggestion} isChange isSubmitting={pendingAction === 'adopt'} onClose={() => setIsChangeConfirmOpen(false)} onConfirm={(suggestion) => void adopt(suggestion, true)} />}
      </main>
    </ClientShell>
  )
}
