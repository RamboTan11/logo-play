import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, WheelEvent as ReactWheelEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ClientShell } from '../components/ClientShell'
import { AdoptionConfirmDialog } from '../components/AdoptionConfirmDialog'
import { adoptLogo, getMyTask, getMyTasks } from '../services/designTasksService'
import { getSavedLogos } from '../services/savedLogosService'
import { useToastStore } from '../stores/useToastStore'
import type { MyTaskDetail, MyTaskListItem, SavedLogoListItem } from '../types/api'
import { formatBeijingDateTime } from '../utils/dateTime'
import { useClientLanguage } from '../i18n/useClientLanguage'

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'

const taskStatusLabels = {
  waiting_assignment: '待接单',
  in_progress: '待上传',
  completed: '已完成',
  canceled: '已取消',
} as const

function displayEmpty(value: string | null): string {
  return value?.trim() || '-'
}

function canModifySuggestion(task: MyTaskListItem): boolean {
  return Boolean(task.adopted_logo_version_id)
    && (task.status === 'waiting_assignment' || task.status === 'in_progress')
}

function scrollSavedLogos(event: ReactKeyboardEvent<HTMLDivElement>): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  const cards = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('.saved-logo-card'))
  if (!cards.length) return
  const currentIndex = cards.indexOf(document.activeElement as HTMLElement)
  const nextIndex = Math.max(0, Math.min(cards.length - 1, currentIndex < 0
    ? (event.key === 'ArrowLeft' ? 0 : 1)
    : currentIndex + (event.key === 'ArrowLeft' ? -1 : 1)))
  if (nextIndex === currentIndex) return
  event.preventDefault()
  cards[nextIndex].focus()
  cards[nextIndex].scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
}

function scrollSavedLogosWithWheel(event: ReactWheelEvent<HTMLDivElement>): void {
  const track = event.currentTarget
  if (track.scrollWidth <= track.clientWidth || event.deltaY === 0) return
  const horizontalDelta = event.deltaX || event.deltaY
  const nextLeft = Math.max(0, Math.min(track.scrollLeft + horizontalDelta, track.scrollWidth - track.clientWidth))
  if (nextLeft === track.scrollLeft) return
  event.preventDefault()
  track.scrollLeft = nextLeft
}

const adoptTooltip = '采用此方案后，我们会继续完善细节，并向你交付最终图片'
const completedDeliveryTooltip = '已有完成交付的方案，无法再次提交。若需变更方案，请联系运营人员处理。'

function SavedLogoCard({ logo, onEdit, onAdopt, isAdoptionLocked }: {
  logo: SavedLogoListItem
  onEdit: () => void
  onAdopt: () => void
  isAdoptionLocked: boolean
}) {
  const { t } = useClientLanguage()
  const tooltipId = 'saved-logo-adopt-lock-' + logo.id
  return (
    <article className="saved-logo-card" tabIndex={-1}>
      <div className="saved-logo-image"><img src={logo.image_url} alt={logo.domain + ' ' + t('收藏方案')} /></div>
      <div className="saved-logo-card-copy"><b>{t('已收藏方案')}</b><span>{logo.domain}</span></div>
      <div className="saved-logo-card-actions">
        <button className="secondary" type="button" aria-label={t('编辑') + ' ' + logo.domain + ' ' + t('收藏方案')} onClick={onEdit}>{t('编辑')}</button>
        <div className={'adopt-tooltip' + (isAdoptionLocked ? ' adopt-disabled-tooltip' : '')} tabIndex={isAdoptionLocked ? 0 : undefined} aria-describedby={isAdoptionLocked ? tooltipId : undefined}>
          <button className="primary" type="button" aria-label={t('采用') + ' ' + logo.domain + ' ' + t('收藏方案')} aria-describedby={isAdoptionLocked ? tooltipId : undefined} disabled={isAdoptionLocked} onClick={onAdopt}>{t('采用')}</button>
          <span id={tooltipId} role="tooltip">{t(isAdoptionLocked ? completedDeliveryTooltip : adoptTooltip)}</span>
        </div>
      </div>
    </article>
  )
}

function TaskThumbnail({ src, alt, onPreview }: {
  src: string | null
  alt: string
  onPreview: (src: string, alt: string) => void
}) {
  const { t } = useClientLanguage()
  if (!src) return <span className="my-task-empty-cell">-</span>
  return (
    <button className="my-task-image-button" type="button" aria-label={t('预览') + ' ' + alt} onClick={() => onPreview(src, alt)}>
      <img src={src} alt={alt} />
    </button>
  )
}

function TaskRow({
  task,
  isOpening,
  isUpdating,
  onViewDetails,
  onModifySuggestion,
  onPreview,
}: {
  task: MyTaskListItem
  isOpening: boolean
  isUpdating: boolean
  onViewDetails: (taskId: string) => void
  onModifySuggestion: (task: MyTaskListItem) => void
  onPreview: (src: string, alt: string) => void
}) {
  const { t } = useClientLanguage()
  return (
    <tr>
      <td className="my-task-domain"><b>{task.domain}</b></td>
      <td><TaskThumbnail src={task.adopted_image_url} alt={task.domain + ' ' + t('采用图片')} onPreview={onPreview} /></td>
      <td className="my-task-suggestion">{displayEmpty(task.adoption_suggestion)}</td>
      <td><time dateTime={task.submitted_at}>{formatBeijingDateTime(task.submitted_at)}</time></td>
      <td><span className={'task-status ' + task.status}>{t(taskStatusLabels[task.status])}</span></td>
      <td><TaskThumbnail src={task.delivery_image_url} alt={task.domain + ' ' + t('精修图片')} onPreview={onPreview} /></td>
      <td>{task.delivery_uploaded_at ? <time dateTime={task.delivery_uploaded_at}>{formatBeijingDateTime(task.delivery_uploaded_at)}</time> : '-'}</td>
      <td>
        <div className="my-task-actions">
          <button className="secondary" type="button" disabled={isOpening || isUpdating} onClick={() => onViewDetails(task.id)}>{t(isOpening ? '加载中...' : '查看详情')}</button>
          {canModifySuggestion(task) && <button className="secondary" type="button" disabled={isOpening || isUpdating} onClick={() => onModifySuggestion(task)}>{t(isUpdating ? '提交中...' : '修改建议')}</button>}
        </div>
      </td>
    </tr>
  )
}

function TaskImage({ src, alt }: { src: string; alt: string }) {
  return <div className="client-task-snapshot-image"><img src={src} alt={alt} /></div>
}

function DeliveryPendingPreview() {
  const { t } = useClientLanguage()
  return <div className="client-task-delivery-pending" role="img" aria-label={t('精修图片未上传')}><span>-</span></div>
}

function TaskDetailsModal({ task, onClose }: { task: MyTaskDetail; onClose: () => void }) {
  const { t } = useClientLanguage()
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div className="my-plans-task-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="my-plans-task-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="task-detail-title">
        <header className="my-plans-task-modal-header"><div><h2 id="task-detail-title">{t('方案详情')}</h2><p>{task.domain}</p></div><button ref={closeButtonRef} className="my-plans-task-modal-close" type="button" aria-label={t('关闭方案详情')} onClick={onClose}>×</button></header>
        <div className="my-plans-task-modal-body customer-task-snapshot-body">
          <section className="client-task-snapshot" aria-labelledby="adopted-logo-title"><h3 id="adopted-logo-title">{t('采用图片')}</h3><TaskImage src={task.adopted_image_url} alt={t('采用图片')} /></section>
          <section className="client-task-snapshot" aria-labelledby="delivery-title"><h3 id="delivery-title">{t('精修图片')}</h3>{task.delivery_image_url ? <TaskImage src={task.delivery_image_url} alt={t('精修图片')} /> : <DeliveryPendingPreview />}</section>
          <dl className="client-task-snapshot-context">
            <div><dt>{t('精修建议')}</dt><dd>{displayEmpty(task.adoption_suggestion)}</dd></div>
            <div><dt>{t('提交时间')}</dt><dd><time dateTime={task.submitted_at}>{formatBeijingDateTime(task.submitted_at)}</time></dd></div>
            <div><dt>{t('上传时间')}</dt><dd>{task.delivery_uploaded_at ? <time dateTime={task.delivery_uploaded_at}>{formatBeijingDateTime(task.delivery_uploaded_at)}</time> : '-'}</dd></div>
          </dl>
        </div>
      </section>
    </div>
  )
}

function ImagePreviewModal({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const { t } = useClientLanguage()
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeButtonRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div className="my-task-image-preview" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="my-task-image-preview-dialog" role="dialog" aria-modal="true" aria-label={alt}>
        <button ref={closeButtonRef} className="my-task-image-preview-close" type="button" aria-label={t('关闭图片预览')} onClick={onClose}>×</button>
        <img src={src} alt={alt} />
      </section>
    </div>
  )
}

export function MyPlansTasksPage() {
  const { t } = useClientLanguage()
  const navigate = useNavigate()
  const [savedLogos, setSavedLogos] = useState<SavedLogoListItem[]>([])
  const [tasks, setTasks] = useState<MyTaskListItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [pageLoadError, setPageLoadError] = useState<string | null>(null)
  const [openingTaskId, setOpeningTaskId] = useState<string | null>(null)
  const [detailLoadError, setDetailLoadError] = useState<{ taskId: string; message: string } | null>(null)
  const [selectedTask, setSelectedTask] = useState<MyTaskDetail | null>(null)
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string } | null>(null)
  const [adoptingSavedLogo, setAdoptingSavedLogo] = useState<SavedLogoListItem | null>(null)
  const [isAdoptingSavedLogo, setIsAdoptingSavedLogo] = useState(false)
  const [isChangingActiveTask, setIsChangingActiveTask] = useState(false)
  const [taskBeingModified, setTaskBeingModified] = useState<MyTaskListItem | null>(null)
  const [isUpdatingSuggestion, setIsUpdatingSuggestion] = useState(false)
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const showToast = useToastStore((state) => state.showToast)
  const isAdoptionLocked = tasks.some((task) => task.status === 'completed')
  const hasActiveTask = tasks.some((task) => task.status === 'waiting_assignment' || task.status === 'in_progress')

  const loadPage = useCallback(async (activeRef?: { current: boolean }) => {
    if (activeRef && !activeRef.current) return
    setIsLoading(true)
    setPageLoadError(null)
    try {
      const [nextSavedLogos, nextTasks] = await Promise.all([getSavedLogos(), getMyTasks()])
      if (activeRef && !activeRef.current) return
      setSavedLogos(nextSavedLogos)
      setTasks(nextTasks)
    } catch {
      if (!activeRef || activeRef.current) {
        setPageLoadError(t('方案与任务加载失败，请稍后重试。'))
      }
    } finally {
      if (!activeRef || activeRef.current) setIsLoading(false)
    }
  }, [t])

  useEffect(() => {
    const active = { current: true }
    queueMicrotask(() => void loadPage(active))
    return () => { active.current = false }
  }, [loadPage])

  const refreshTasks = async () => {
    const nextTasks = await getMyTasks()
    setTasks(nextTasks)
  }

  const openTask = async (taskId: string) => {
    if (openingTaskId) return
    setOpeningTaskId(taskId)
    setDetailLoadError(null)
    try {
      setSelectedTask(await getMyTask(taskId))
    } catch {
      setDetailLoadError({ taskId, message: t('方案详情加载失败，请稍后重试。') })
    } finally {
      setOpeningTaskId(null)
    }
  }

  const adoptSavedLogo = async (suggestion: string) => {
    if (!adoptingSavedLogo || isAdoptingSavedLogo) return
    setIsAdoptingSavedLogo(true)
    try {
      const result = await adoptLogo(
        adoptingSavedLogo.logo_version_id,
        suggestion.trim() || null,
        isMockMode
          ? { domain: adoptingSavedLogo.domain, initialLogoVersionId: adoptingSavedLogo.logo_version_id, aiEditInputs: [] }
          : undefined,
        isChangingActiveTask,
      )
      if (result === 'completed_task_exists') {
        setAdoptingSavedLogo(null)
        showToast(t('已有完成交付的方案，请前往'), { label: t('我的方案'), to: '/my-plans', suffix: t('查看') })
        return
      }
      if (result === 'active_task_confirmation_required') {
        setIsChangingActiveTask(true)
        return
      }
      setAdoptingSavedLogo(null)
      setIsChangingActiveTask(false)
      showToast(t('采用成功'))
      await refreshTasks()
    } catch {
      showToast(t('采用失败。'))
    } finally {
      setIsAdoptingSavedLogo(false)
    }
  }

  const updateSuggestion = async (suggestion: string) => {
    if (!taskBeingModified || isUpdatingSuggestion) return
    setIsUpdatingSuggestion(true)
    setSuggestionError(null)
    try {
      const result = await adoptLogo(
        taskBeingModified.adopted_logo_version_id,
        suggestion.trim() || null,
        isMockMode
          ? { domain: taskBeingModified.domain, initialLogoVersionId: taskBeingModified.adopted_logo_version_id, aiEditInputs: [] }
          : undefined,
        true,
      )
      if (result === 'completed_task_exists') {
        setTaskBeingModified(null)
        setSuggestionError(null)
        showToast(t('已有完成交付的方案，请前往'), { label: t('我的方案'), to: '/my-plans', suffix: t('查看') })
        await refreshTasks()
        return
      }
      if (result === 'active_task_confirmation_required') return
      setTaskBeingModified(null)
      setSuggestionError(null)
      showToast(t('修改建议已提交'))
      await refreshTasks()
    } catch {
      setSuggestionError(t('修改建议失败，请稍后重试。'))
    } finally {
      setIsUpdatingSuggestion(false)
    }
  }

  return (
    <ClientShell>
      <main className="client-main my-plans-main">
        {isLoading ? <p className="my-plans-loading">{t('正在加载方案与任务...')}</p> : pageLoadError ? <section className="my-plans-load-error" role="alert"><p>{pageLoadError}</p><button className="secondary" type="button" onClick={() => void loadPage()}>{t('重试')}</button></section> : <>
          <section className="my-plans-section" aria-labelledby="saved-title"><header><h2 id="saved-title">{t('收藏方案')}</h2></header>{savedLogos.length ? <div className="saved-logo-grid" role="region" aria-label={t('收藏方案横向列表')} tabIndex={0} onKeyDown={scrollSavedLogos} onWheel={scrollSavedLogosWithWheel}>{savedLogos.map((logo) => <SavedLogoCard key={logo.id} logo={logo} isAdoptionLocked={isAdoptionLocked} onEdit={() => navigate('/edit/' + encodeURIComponent(logo.logo_version_id))} onAdopt={() => { setIsChangingActiveTask(hasActiveTask); setAdoptingSavedLogo(logo) }} />)}</div> : <p className="my-plans-empty">{t('暂无收藏方案')}</p>}</section>
          <section className="my-plans-section" aria-labelledby="tasks-title">
            <header><h2 id="tasks-title">{t('方案列表')}</h2></header>
            {tasks.length ? <div className="my-plans-table-wrap"><table className="my-plans-table"><thead><tr>{['域名', '采用图片', '精修建议', '提交时间', '状态', '精修图片', '上传时间', '操作'].map((heading) => <th key={heading}>{t(heading)}</th>)}</tr></thead><tbody>{tasks.map((task) => <TaskRow key={task.id} task={task} isOpening={openingTaskId === task.id} isUpdating={isUpdatingSuggestion && taskBeingModified?.id === task.id} onViewDetails={(taskId) => void openTask(taskId)} onModifySuggestion={setTaskBeingModified} onPreview={(src, alt) => setPreviewImage({ src, alt })} />)}</tbody></table></div> : <p className="my-plans-empty">{t('暂无任务')}</p>}
          </section>
        </>}
      </main>
      {detailLoadError && <section className="my-plans-detail-error" role="alert" aria-live="polite"><p>{detailLoadError.message}</p><button className="secondary" type="button" onClick={() => void openTask(detailLoadError.taskId)} disabled={openingTaskId === detailLoadError.taskId}>{t('重试')}</button></section>}
      {selectedTask && <TaskDetailsModal task={selectedTask} onClose={() => setSelectedTask(null)} />}
      {previewImage && <ImagePreviewModal src={previewImage.src} alt={previewImage.alt} onClose={() => setPreviewImage(null)} />}
      {adoptingSavedLogo && <AdoptionConfirmDialog domain={adoptingSavedLogo.domain} initialSuggestion="" isChange={isChangingActiveTask} isSubmitting={isAdoptingSavedLogo} onClose={() => { setAdoptingSavedLogo(null); setIsChangingActiveTask(false) }} onConfirm={(suggestion) => void adoptSavedLogo(suggestion)} />}
      {taskBeingModified && <AdoptionConfirmDialog domain={taskBeingModified.domain} initialSuggestion={taskBeingModified.adoption_suggestion ?? ''} isChange isSubmitting={isUpdatingSuggestion} errorMessage={suggestionError} onClose={() => { setTaskBeingModified(null); setSuggestionError(null) }} onConfirm={(suggestion) => void updateSuggestion(suggestion)} />}
    </ClientShell>
  )
}
