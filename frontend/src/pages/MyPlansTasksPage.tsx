import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode, WheelEvent as ReactWheelEvent } from 'react'
import { createPortal } from 'react-dom'
import { Smartphone } from 'lucide-react'
import { ClientShell } from '../components/ClientShell'
import { CachedImage, preloadImage } from '../components/CachedImage'
import { AdoptionConfirmDialog } from '../components/AdoptionConfirmDialog'
import { ResultEditDialog } from '../components/ResultEditDialog'
import type { ResultEditVersion } from '../components/ResultEditDialog'
import { adoptLogo, getMyTask, getMyTasks, submitTaskFeedback } from '../services/designTasksService'
import { createSingleEditGeneration, getSingleEditStatus } from '../services/generationsService'
import { getSavedLogos, updateSavedLogo } from '../services/savedLogosService'
import { useToastStore } from '../stores/useToastStore'
import type { MyTaskDetail, MyTaskListItem, SavedLogoListItem } from '../types/api'
import { formatBeijingDateTime } from '../utils/dateTime'
import { useClientLanguage } from '../i18n/useClientLanguage'

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'
const iphoneMockupReferenceUrl = `${import.meta.env.BASE_URL}mockups/iphone-home-screen.webp`
const defaultEditInstruction = '重新生成当前相似风格的 logo 图。'

const taskStatusLabels = {
  waiting_assignment: '待接单',
  in_progress: '待上传',
  completed: '已交付',
  canceled: '已取消',
} as const

function displayEmpty(value: string | null): string {
  return value?.trim() || '-'
}

function TextPreview({ value }: { value: string | null }) {
  const text = value?.trim() || '-'
  if (text.length <= 5) return <span>{text}</span>
  return <span className="list-text-preview" tabIndex={0}>{text.slice(0, 5)}...<span role="tooltip">{text}</span></span>
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

function scheduleSavedLogosWithWheel(
  event: ReactWheelEvent<HTMLDivElement>,
  pendingDelta: { current: number },
  frame: { current: number | null },
): void {
  const track = event.currentTarget
  if (track.scrollWidth <= track.clientWidth || event.deltaY === 0) return
  const horizontalDelta = event.deltaX || event.deltaY
  event.preventDefault()
  event.stopPropagation()
  pendingDelta.current += horizontalDelta
  if (frame.current !== null) return
  frame.current = window.requestAnimationFrame(() => {
    const delta = pendingDelta.current
    pendingDelta.current = 0
    frame.current = null
    const nextLeft = Math.max(0, Math.min(track.scrollLeft + delta, track.scrollWidth - track.clientWidth))
    if (nextLeft !== track.scrollLeft) track.scrollLeft = nextLeft
  })
}

const adoptTooltip = '采用此方案后，我们会继续完善细节，并向您交付最终图片'
const completedDeliveryTooltip = '已有完成交付的方案，无法再次提交。若需变更方案，请联系运营人员处理。'
const taskStatusLoadingTooltip = '正在加载当前任务状态。'

function FloatingDisabledTooltip({ id, message, children }: { id: string; message: string; children: ReactNode }) {
  const anchorRef = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState<{ left: number; top: number; below: boolean } | null>(null)

  const updatePosition = useCallback(() => {
    const anchor = anchorRef.current
    if (!anchor) return
    const rect = anchor.getBoundingClientRect()
    const tooltipWidth = Math.min(288, window.innerWidth - 24)
    const left = Math.max(12, Math.min(rect.right + 8, window.innerWidth - tooltipWidth - 12))
    const below = rect.top < 112
    setPosition({ left, top: below ? rect.bottom + 8 : rect.top - 8, below })
  }, [])

  useEffect(() => {
    if (!visible) return
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [updatePosition, visible])

  const showTooltip = () => {
    updatePosition()
    setVisible(true)
  }

  const tooltip = visible && position && typeof document !== 'undefined'
    ? createPortal(<span id={id} className="adopt-disabled-tooltip-floating" role="tooltip" style={{ left: position.left, top: position.top, transform: position.below ? 'none' : 'translateY(-100%)' }}>{message}</span>, document.body)
    : null

  return <div ref={anchorRef} className="adopt-tooltip adopt-disabled-tooltip" tabIndex={0} aria-describedby={id} onMouseEnter={showTooltip} onMouseLeave={() => setVisible(false)} onFocus={showTooltip} onBlur={() => setVisible(false)}>{children}{tooltip}</div>
}

function SavedLogoCard({ logo, onEdit, onAdopt, onMockupPreview, isAdoptionLocked, isAdoptionPending }: {
  logo: SavedLogoListItem
  onEdit: () => void
  onAdopt: () => void
  onMockupPreview: () => void
  isAdoptionLocked: boolean
  isAdoptionPending: boolean
}) {
  const { t } = useClientLanguage()
  const tooltipId = 'saved-logo-adopt-lock-' + logo.id
  const isAdoptionDisabled = isAdoptionLocked || isAdoptionPending
  const tooltip = isAdoptionLocked ? completedDeliveryTooltip : isAdoptionPending
    ? taskStatusLoadingTooltip
    : adoptTooltip
  return (
    <article className="saved-logo-card" tabIndex={-1}>
      <div className="saved-logo-image">
        <CachedImage src={logo.image_url} alt={logo.domain + ' ' + t('收藏方案')} thumbnail loading="eager" />
        <div className="saved-logo-mockup-tooltip">
          <button className="saved-logo-mockup-trigger" type="button" aria-label={t('查看 logo 应用样机预览')} onClick={onMockupPreview}>
            <Smartphone size={16} strokeWidth={2.2} aria-hidden="true" />
          </button>
          <span role="tooltip">{t('查看 logo 应用样机预览')}</span>
        </div>
      </div>
      <div className="saved-logo-card-copy"><b>{t('已收藏方案')}</b><span>{logo.domain}</span></div>
      <div className="saved-logo-card-actions">
        <button className="secondary" type="button" aria-label={t('编辑') + ' ' + logo.domain + ' ' + t('收藏方案')} onClick={onEdit}>{t('编辑')}</button>
        {isAdoptionDisabled
          ? <FloatingDisabledTooltip id={tooltipId} message={t(tooltip)}><button className="primary" type="button" aria-label={t('采用') + ' ' + logo.domain + ' ' + t('收藏方案')} aria-describedby={tooltipId} disabled onClick={onAdopt}>{t('采用')}</button></FloatingDisabledTooltip>
          : <div className="adopt-tooltip"><button className="primary" type="button" aria-label={t('采用') + ' ' + logo.domain + ' ' + t('收藏方案')} disabled={isAdoptionDisabled} onClick={onAdopt}>{t('采用')}</button><span role="tooltip">{t(tooltip)}</span></div>}
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
      <CachedImage src={src} alt={alt} thumbnail loading="eager" />
    </button>
  )
}

function AppMockup({ imageUrl, domain, thumbnail = true, progressive = false, className = '' }: {
  imageUrl: string
  domain: string
  thumbnail?: boolean
  progressive?: boolean
  className?: string
}) {
  const { t } = useClientLanguage()
  const appName = domain.split('.')[0]?.toUpperCase() || domain.toUpperCase()
  return (
    <div className={`my-task-mockup ${className}`} role="img" aria-label={`${domain} ${t('应用样机预览')}`}>
      <img className="my-task-mockup-reference" src={iphoneMockupReferenceUrl} alt="" aria-hidden="true" loading="eager" decoding="async" />
      <div className="my-task-mockup-selected-app">
        <div className="my-task-mockup-selected-icon"><CachedImage src={imageUrl} alt={`${domain} ${t('采用图片')}`} thumbnail={thumbnail} progressive={progressive} loading="eager" /></div>
        <span>{appName}</span>
      </div>
    </div>
  )
}

function TaskMockupThumbnail({ src, domain, onPreview }: {
  src: string | null
  domain: string
  onPreview: (src: string, domain: string) => void
}) {
  const { t } = useClientLanguage()
  if (!src) return <span className="my-task-empty-cell">-</span>
  return (
    <button className="my-task-mockup-button" type="button" aria-label={t('预览') + ' ' + domain + ' ' + t('应用样机预览')} onClick={() => onPreview(src, domain)}>
      <AppMockup imageUrl={src} domain={domain} />
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
  onMockupPreview,
  onFeedback,
}: {
  task: MyTaskListItem
  isOpening: boolean
  isUpdating: boolean
  onViewDetails: (taskId: string) => void
  onModifySuggestion: (task: MyTaskListItem) => void
  onPreview: (src: string, alt: string) => void
  onMockupPreview: (src: string, domain: string) => void
  onFeedback: (task: MyTaskListItem) => void
}) {
  const { t } = useClientLanguage()
  return (
    <tr>
      <td className="my-task-domain"><b>{task.domain}</b></td>
      <td><TaskThumbnail src={task.adopted_image_url} alt={task.domain + ' ' + t('采用图片')} onPreview={onPreview} /></td>
      <td className="my-task-suggestion"><TextPreview value={task.adoption_suggestion} /></td>
      <td><time dateTime={task.submitted_at}>{formatBeijingDateTime(task.submitted_at)}</time></td>
      <td><span className={'task-status ' + task.status}>{t(taskStatusLabels[task.status])}</span></td>
      <td><TaskThumbnail src={task.delivery_image_url} alt={task.domain + ' ' + t('精修图片')} onPreview={onPreview} /></td>
      <td>{task.delivery_uploaded_at ? <time dateTime={task.delivery_uploaded_at}>{formatBeijingDateTime(task.delivery_uploaded_at)}</time> : '-'}</td>
      <td><TaskMockupThumbnail src={task.delivery_image_url} domain={task.domain} onPreview={onMockupPreview} /></td>
      <td>
        <div className="my-task-actions">
          <button className="secondary" type="button" disabled={isOpening || isUpdating} onClick={() => onViewDetails(task.id)}>{t(isOpening ? '加载中...' : '查看详情')}</button>
          {canModifySuggestion(task) && <button className="secondary" type="button" disabled={isOpening || isUpdating} onClick={() => onModifySuggestion(task)}>{t(isUpdating ? '提交中...' : '修改建议')}</button>}
          {task.status === 'completed' && <button className="secondary" type="button" disabled={isOpening || isUpdating} onClick={() => onFeedback(task)}>{t(task.customer_feedback ? '修改反馈' : '反馈意见')}</button>}
        </div>
      </td>
    </tr>
  )
}

function TaskImage({ src, alt }: { src: string; alt: string }) {
  return <div className="client-task-snapshot-image"><CachedImage src={src} alt={alt} loading="eager" progressive /></div>
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
            <div><dt>{t('精修建议')}</dt><dd><TextPreview value={task.adoption_suggestion} /></dd></div>
            <div><dt>{t('反馈意见')}</dt><dd><TextPreview value={task.customer_feedback} /></dd></div>
            <div><dt>{t('提交时间')}</dt><dd><time dateTime={task.submitted_at}>{formatBeijingDateTime(task.submitted_at)}</time></dd></div>
            <div><dt>{t('上传时间')}</dt><dd>{task.delivery_uploaded_at ? <time dateTime={task.delivery_uploaded_at}>{formatBeijingDateTime(task.delivery_uploaded_at)}</time> : '-'}</dd></div>
          </dl>
        </div>
      </section>
    </div>
  )
}

function FeedbackDialog({ task, busy, onClose, onSubmit }: { task: MyTaskListItem; busy: boolean; onClose: () => void; onSubmit: (feedback: string) => void }) {
  const { t } = useClientLanguage()
  const [feedback, setFeedback] = useState(task.customer_feedback ?? '')
  return <div className="feedback-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}><section className="feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="feedback-title"><header><div><h2 id="feedback-title">{t('交付反馈')}</h2><p>{task.domain} · {t('可随时修改')}</p></div><button type="button" aria-label={t('关闭')} disabled={busy} onClick={onClose}>×</button></header><div className="feedback-dialog-body"><label><span>{t('反馈意见')}</span><textarea maxLength={4000} value={feedback} disabled={busy} onChange={(event) => setFeedback(event.target.value)} placeholder={t('请输入您的反馈意见')} /></label></div><footer><button className="secondary" type="button" disabled={busy} onClick={onClose}>{t('取消')}</button><button className="primary" type="button" disabled={busy || !feedback.trim()} onClick={() => onSubmit(feedback)}>{busy ? t('提交中...') : t('保存反馈')}</button></footer></section></div>
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
        <CachedImage src={src} alt={alt} loading="eager" progressive />
      </section>
    </div>
  )
}

function MockupPreviewModal({ src, domain, onClose }: { src: string; domain: string; onClose: () => void }) {
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
      <section className="my-task-mockup-preview-dialog" role="dialog" aria-modal="true" aria-label={`${domain} ${t('应用样机预览')}`}>
        <button ref={closeButtonRef} className="my-task-image-preview-close" type="button" aria-label={t('关闭图片预览')} onClick={onClose}>×</button>
        <AppMockup imageUrl={src} domain={domain} thumbnail progressive className="my-task-mockup-large" />
      </section>
    </div>
  )
}

function SavedLogosLoading() {
  const { t } = useClientLanguage()
  return <div className="my-plans-skeleton saved" aria-label={t('正在加载收藏方案')} aria-busy="true"><i /><i /><i /></div>
}

function TasksLoading() {
  const { t } = useClientLanguage()
  return <div className="my-plans-skeleton tasks" aria-label={t('正在加载方案列表')} aria-busy="true"><i /><i /><i /></div>
}

export function MyPlansTasksPage() {
  const { t } = useClientLanguage()
  const [savedLogos, setSavedLogos] = useState<SavedLogoListItem[]>([])
  const [tasks, setTasks] = useState<MyTaskListItem[]>([])
  const [isSavedLogosLoading, setIsSavedLogosLoading] = useState(true)
  const [isTasksLoading, setIsTasksLoading] = useState(true)
  const [savedLogosLoadError, setSavedLogosLoadError] = useState<string | null>(null)
  const [tasksLoadError, setTasksLoadError] = useState<string | null>(null)
  const [openingTaskId, setOpeningTaskId] = useState<string | null>(null)
  const [detailLoadError, setDetailLoadError] = useState<{ taskId: string; message: string } | null>(null)
  const [selectedTask, setSelectedTask] = useState<MyTaskDetail | null>(null)
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string } | null>(null)
  const [previewMockup, setPreviewMockup] = useState<{ src: string; domain: string } | null>(null)
  const [adoptingSavedLogo, setAdoptingSavedLogo] = useState<SavedLogoListItem | null>(null)
  const [isAdoptingSavedLogo, setIsAdoptingSavedLogo] = useState(false)
  const [editingSavedLogo, setEditingSavedLogo] = useState<SavedLogoListItem | null>(null)
  const [isEditingSavedLogo, setIsEditingSavedLogo] = useState(false)
  const [isChangingActiveTask, setIsChangingActiveTask] = useState(false)
  const [taskBeingModified, setTaskBeingModified] = useState<MyTaskListItem | null>(null)
  const [isUpdatingSuggestion, setIsUpdatingSuggestion] = useState(false)
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const [feedbackTask, setFeedbackTask] = useState<MyTaskListItem | null>(null)
  const savedWheelPendingRef = useRef(0)
  const savedWheelFrameRef = useRef<number | null>(null)
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false)
  const showToast = useToastStore((state) => state.showToast)
  const isAdoptionLocked = tasks.some((task) => task.status === 'completed')
  const hasActiveTask = tasks.some((task) => task.status === 'waiting_assignment' || task.status === 'in_progress')

  const loadPage = useCallback(async (activeRef?: { current: boolean }) => {
    if (activeRef && !activeRef.current) return
    setIsSavedLogosLoading(true)
    setIsTasksLoading(true)
    setSavedLogosLoadError(null)
    setTasksLoadError(null)
    await Promise.all([
      getSavedLogos().then(
        (nextSavedLogos) => {
          if (!activeRef || activeRef.current) setSavedLogos(nextSavedLogos)
        },
        () => {
          if (!activeRef || activeRef.current) setSavedLogosLoadError(t('收藏方案加载失败，请稍后重试。'))
        },
      ).finally(() => {
        if (!activeRef || activeRef.current) setIsSavedLogosLoading(false)
      }),
      getMyTasks().then(
        (nextTasks) => {
          if (!activeRef || activeRef.current) setTasks(nextTasks)
        },
        () => {
          if (!activeRef || activeRef.current) setTasksLoadError(t('方案列表加载失败，请稍后重试。'))
        },
      ).finally(() => {
        if (!activeRef || activeRef.current) setIsTasksLoading(false)
      }),
    ])
  }, [t])

  useEffect(() => {
    const active = { current: true }
    queueMicrotask(() => void loadPage(active))
    return () => { active.current = false }
  }, [loadPage])

  useEffect(() => {
    preloadImage(iphoneMockupReferenceUrl)
  }, [])

  useEffect(() => () => {
    if (savedWheelFrameRef.current !== null) window.cancelAnimationFrame(savedWheelFrameRef.current)
  }, [])

  const scrollSavedLogosWithWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    scheduleSavedLogosWithWheel(event, savedWheelPendingRef, savedWheelFrameRef)
  }

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

  const updateFeedback = async (feedback: string) => {
    if (!feedbackTask || isSubmittingFeedback) return
    setIsSubmittingFeedback(true)
    try {
      const updated = await submitTaskFeedback(feedbackTask.id, feedback)
      setTasks((current) => current.map((task) => task.id === updated.id ? updated : task))
      setFeedbackTask(null)
      showToast(t('反馈意见已保存'))
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('反馈提交失败，请稍后重试。'))
    } finally { setIsSubmittingFeedback(false) }
  }

  const generateSavedLogoEdit = async (instruction: string): Promise<ResultEditVersion | null> => {
    if (!editingSavedLogo || isEditingSavedLogo) return null
    setIsEditingSavedLogo(true)
    try {
      const accepted = await createSingleEditGeneration(
        editingSavedLogo.logo_version_id,
        instruction.trim() || defaultEditInstruction,
      )
      if (isMockMode) return { id: accepted.request_id, imageUrl: null }
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
      setIsEditingSavedLogo(false)
    }
  }

  const useEditedSavedLogo = async (version: ResultEditVersion) => {
    if (!editingSavedLogo) return
    setIsEditingSavedLogo(true)
    try {
      const updated = await updateSavedLogo(editingSavedLogo.id, version.id)
      setSavedLogos((current) => current.map((logo) => logo.id === editingSavedLogo.id
        ? { ...updated.saved_logo, image_url: version.imageUrl ?? updated.saved_logo.image_url }
        : logo))
      setEditingSavedLogo(null)
    } finally {
      setIsEditingSavedLogo(false)
    }
  }

  return (
    <ClientShell>
      <main className="client-main my-plans-main">
        <section className="my-plans-section" aria-labelledby="saved-title"><header><div className="my-plans-section-heading"><h2 id="saved-title">{t('收藏方案')}</h2><p>{t('点击图片右上角角标可查看应用样机预览效果')}</p></div></header>{isSavedLogosLoading ? <SavedLogosLoading /> : savedLogosLoadError ? <section className="my-plans-load-error" role="alert"><p>{savedLogosLoadError}</p><button className="secondary" type="button" onClick={() => void loadPage()}>{t('重试')}</button></section> : savedLogos.length ? <div className="saved-logo-grid" role="region" aria-label={t('收藏方案横向列表')} tabIndex={0} onKeyDown={scrollSavedLogos} onWheel={scrollSavedLogosWithWheel}>{savedLogos.map((logo) => <SavedLogoCard key={logo.id} logo={logo} isAdoptionLocked={isAdoptionLocked} isAdoptionPending={isTasksLoading || tasksLoadError !== null} onEdit={() => setEditingSavedLogo(logo)} onAdopt={() => { setIsChangingActiveTask(hasActiveTask); setAdoptingSavedLogo(logo) }} onMockupPreview={() => setPreviewMockup({ src: logo.image_url, domain: logo.domain })} />)}</div> : <p className="my-plans-empty">{t('暂无收藏方案')}</p>}</section>
          <section className="my-plans-section" aria-labelledby="tasks-title">
            <header><h2 id="tasks-title">{t('方案列表')}</h2></header>
            {isTasksLoading ? <TasksLoading /> : tasksLoadError ? <section className="my-plans-load-error" role="alert"><p>{tasksLoadError}</p><button className="secondary" type="button" onClick={() => void loadPage()}>{t('重试')}</button></section> : tasks.length ? <div className="my-plans-table-wrap"><table className="my-plans-table"><thead><tr>{['域名', '采用图片', '精修建议', '提交时间', '状态', '精修图片', '上传时间', '应用样机预览', '操作'].map((heading) => <th key={heading}>{t(heading)}</th>)}</tr></thead><tbody>{tasks.map((task) => <TaskRow key={task.id} task={task} isOpening={openingTaskId === task.id} isUpdating={isUpdatingSuggestion && taskBeingModified?.id === task.id} onViewDetails={(taskId) => void openTask(taskId)} onModifySuggestion={setTaskBeingModified} onPreview={(src, alt) => setPreviewImage({ src, alt })} onMockupPreview={(src, domain) => setPreviewMockup({ src, domain })} onFeedback={setFeedbackTask} />)}</tbody></table></div> : <p className="my-plans-empty">{t('暂无任务')}</p>}
          </section>
      </main>
      {detailLoadError && <section className="my-plans-detail-error" role="alert" aria-live="polite"><p>{detailLoadError.message}</p><button className="secondary" type="button" onClick={() => void openTask(detailLoadError.taskId)} disabled={openingTaskId === detailLoadError.taskId}>{t('重试')}</button></section>}
      {selectedTask && <TaskDetailsModal task={selectedTask} onClose={() => setSelectedTask(null)} />}
      {previewImage && <ImagePreviewModal src={previewImage.src} alt={previewImage.alt} onClose={() => setPreviewImage(null)} />}
      {previewMockup && <MockupPreviewModal src={previewMockup.src} domain={previewMockup.domain} onClose={() => setPreviewMockup(null)} />}
      {editingSavedLogo && <ResultEditDialog domain={editingSavedLogo.domain} source={{ id: editingSavedLogo.logo_version_id, imageUrl: editingSavedLogo.image_url }} variant={0} isPageBusy={isEditingSavedLogo} onClose={() => setEditingSavedLogo(null)} onGenerate={generateSavedLogoEdit} onUse={useEditedSavedLogo} />}
      {adoptingSavedLogo && <AdoptionConfirmDialog domain={adoptingSavedLogo.domain} initialSuggestion="" isChange={isChangingActiveTask} isSubmitting={isAdoptingSavedLogo} onClose={() => { setAdoptingSavedLogo(null); setIsChangingActiveTask(false) }} onConfirm={(suggestion) => void adoptSavedLogo(suggestion)} />}
      {taskBeingModified && <AdoptionConfirmDialog domain={taskBeingModified.domain} initialSuggestion={taskBeingModified.adoption_suggestion ?? ''} isChange isSubmitting={isUpdatingSuggestion} errorMessage={suggestionError} onClose={() => { setTaskBeingModified(null); setSuggestionError(null) }} onConfirm={(suggestion) => void updateSuggestion(suggestion)} />}
      {feedbackTask && <FeedbackDialog task={feedbackTask} busy={isSubmittingFeedback} onClose={() => setFeedbackTask(null)} onSubmit={(feedback) => void updateFeedback(feedback)} />}
    </ClientShell>
  )
}
