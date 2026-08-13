import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Download, RotateCcw, Upload, UserCheck } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { AdminNavigation } from '../components/AdminNavigation'
import { GlobalToast } from '../components/GlobalToast'
import {
  acceptTask,
  downloadTaskImage,
  downloadTaskExport,
  getTaskCenterTask,
  getTaskCenterTasks,
  uploadTaskDeliveryImage,
  validateDeliveryImage,
} from '../services/taskCenterService'
import type { TaskCenterDetail, TaskCenterItem, TaskCenterStatus } from '../services/taskCenterService'
import { useToastStore } from '../stores/useToastStore'
import { formatBeijingDateTime } from '../utils/dateTime'

const labels = { waiting_assignment: '待接单', in_progress: '处理中', completed: '已完成', canceled: '已取消' } as const
const statusOptions: ReadonlyArray<{ value: TaskCenterStatus; label: string }> = [
  { value: 'waiting_assignment', label: '待接单' },
  { value: 'in_progress', label: '处理中' },
  { value: 'completed', label: '已完成' },
  { value: 'canceled', label: '已取消' },
]
const pageSize = 15
type PageToken = number | 'leading-ellipsis' | 'trailing-ellipsis'
type DateRange = { start: string; end: string }
type PendingDelivery = { task: TaskCenterItem; file: File; previewUrl: string }

function empty(value: string | null): string { return value?.trim() || '-' }
function localDate(value: string): string { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10) }
function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as { response?: { data?: { message?: string } } }).response
    if (response?.data?.message) return response.data.message
  }
  return error instanceof Error ? error.message : fallback
}

function errorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object' || !('response' in error)) return null
  const response = (error as { response?: { data?: { metadata?: { error_code?: unknown } } } }).response
  const code = response?.data?.metadata?.error_code
  return typeof code === 'string' ? code : null
}

function isTaskChanged(error: unknown): boolean {
  return ['task_changed', 'task_canceled', 'task_transition_rejected', 'task_not_in_progress'].includes(errorCode(error) ?? '')
}

function customerAccessToast(status: TaskCenterItem['customer_access_status']): string | null {
  if (status === 'expired') return '该用户的访客链接已到期，请先恢复使用'
  if (status === 'stopped') return '该用户的访客链接已关停，请先恢复使用'
  return null
}

function paginationTokens(currentPage: number, totalPages: number): PageToken[] {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1)
  if (currentPage <= 4) return [1, 2, 3, 4, 5, 'trailing-ellipsis', totalPages]
  if (currentPage >= totalPages - 3) return [1, 'leading-ellipsis', totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages]
  return [1, 'leading-ellipsis', currentPage - 1, currentPage, currentPage + 1, 'trailing-ellipsis', totalPages]
}

function DeliveryPendingPreview() {
  return <div className="client-task-delivery-pending task-center-delivery-pending" role="img" aria-label="精修终稿待上传"><span>待上传</span></div>
}

function TaskDetailModal({ task, isBusy, onAccept, onClose, onDownload, onUpload }: {
  task: TaskCenterDetail
  isBusy: boolean
  onAccept: () => void
  onClose: () => void
  onDownload: () => Promise<void>
  onUpload: (file: File) => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [isDownloading, setIsDownloading] = useState(false)
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return <div className="task-detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="task-detail-dialog" role="dialog" aria-modal="true" aria-labelledby="task-detail-title">
      <header className="task-detail-head"><div><h2 id="task-detail-title">任务详情</h2><p>{task.domain}</p></div><button ref={closeRef} className="task-detail-close" type="button" aria-label="关闭任务详情" onClick={onClose}>×</button></header>
      <div className="task-detail-body">
        <div className="task-detail-facts"><div className="task-detail-fact"><span>客户名称</span><b>{task.customer_name}</b></div><div className="task-detail-fact"><span>当前状态</span><b>{labels[task.status]}</b></div></div>
        <div className="task-detail-images">
          <article className="task-detail-image"><div className="task-detail-image-head"><h3>选择方案</h3><button type="button" disabled={isDownloading} aria-label="下载选择方案" title="下载选择方案" onClick={() => { setIsDownloading(true); void onDownload().finally(() => setIsDownloading(false)) }}><Download size={15} aria-hidden="true" /></button></div><div className="task-detail-image-frame"><img src={task.adopted_image_url} alt="选择方案" draggable title="可拖动图片到支持的应用" onDragStart={(event) => { event.dataTransfer.effectAllowed = 'copy' }} /></div></article>
          <article className="task-detail-image"><div className="task-detail-image-head"><h3>精修终稿</h3></div>{task.delivery_image_url ? <div className="task-detail-image-frame"><img src={task.delivery_image_url} alt="精修终稿" /></div> : <DeliveryPendingPreview />}</article>
        </div>
        <div className="task-detail-texts"><div className="task-detail-text"><span>人工精修建议</span><b>{empty(task.adoption_suggestion)}</b></div></div>
      </div>
      {(task.status === 'waiting_assignment' || task.status === 'in_progress') && <footer className="task-detail-actions">
        <button className="internal-button" type="button" disabled={isBusy} onClick={onClose}>取消</button>
        {task.status === 'waiting_assignment' && <button className="internal-button primary" type="button" disabled={isBusy} onClick={onAccept}><UserCheck size={16} aria-hidden="true" />{isBusy ? '处理中...' : '接单'}</button>}
        {task.status === 'in_progress' && <label className={`internal-button primary task-detail-upload${isBusy ? ' disabled' : ''}`}><Upload size={16} aria-hidden="true" />{isBusy ? '上传中...' : '上传图片'}<input className="sr-only" type="file" disabled={isBusy} accept="image/png,image/jpeg,.png,.jpg,.jpeg" onChange={(event) => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) onUpload(file) }} /></label>}
      </footer>}
    </section>
  </div>
}

function DeliveryConfirmModal({ pending, isUploading, onCancel, onConfirm }: {
  pending: PendingDelivery
  isUploading: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isUploading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isUploading, onCancel])

  return <div className="delivery-confirm-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !isUploading) onCancel() }}>
    <section className="delivery-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delivery-confirm-title" aria-describedby="delivery-confirm-description">
      <header><div><h2 id="delivery-confirm-title">确认上传交付图片</h2><p id="delivery-confirm-description">{pending.task.customer_name} · {pending.task.domain}</p></div><button ref={closeRef} type="button" aria-label="关闭上传确认" disabled={isUploading} onClick={onCancel}>×</button></header>
      <div className="delivery-confirm-body">
        <div className="delivery-confirm-preview"><img src={pending.previewUrl} alt="已选择的交付图片" /></div>
        <div className="delivery-confirm-file"><span>已选择图片</span><b>{pending.file.name}</b><small>{(pending.file.size / 1024 / 1024).toFixed(2)} MB</small></div>
      </div>
      <footer><button className="internal-button" type="button" disabled={isUploading} onClick={onCancel}>取消</button><button className="internal-button primary" type="button" disabled={isUploading} onClick={onConfirm}>{isUploading ? '上传中...' : '确认上传'}</button></footer>
    </section>
  </div>
}

function TaskChangedModal({ onCancel, onRefresh }: { onCancel: () => void; onRefresh: () => void }) {
  const refreshRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { refreshRef.current?.focus() }, [])
  return <div className="task-changed-backdrop" role="presentation">
    <section className="task-changed-dialog" role="dialog" aria-modal="true" aria-labelledby="task-changed-title">
      <div className="task-changed-body"><h2 id="task-changed-title">任务已发生变更</h2></div>
      <footer><button className="internal-button" type="button" onClick={onCancel}>取消</button><button ref={refreshRef} className="internal-button primary" type="button" onClick={onRefresh}>最新任务</button></footer>
    </section>
  </div>
}

export function TaskCenterPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [searchParams, setSearchParams] = useSearchParams()
  const [tasks, setTasks] = useState<TaskCenterItem[]>([])
  const [total, setTotal] = useState(0)
  const [selectedTask, setSelectedTask] = useState<TaskCenterDetail | null>(null)
  const [statusFilters, setStatusFilters] = useState<TaskCenterStatus[]>([])
  const [timePreset, setTimePreset] = useState('all')
  const [dateRange, setDateRange] = useState<DateRange>({ start: '', end: '' })
  const [draftRange, setDraftRange] = useState<DateRange>({ start: '', end: '' })
  const [isTimeOpen, setIsTimeOpen] = useState(false)
  const [dateError, setDateError] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [isExporting, setIsExporting] = useState(false)
  const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
  const [pendingDelivery, setPendingDelivery] = useState<PendingDelivery | null>(null)
  const [isTaskChangedOpen, setIsTaskChangedOpen] = useState(false)
  const timeTriggerRef = useRef<HTMLButtonElement>(null)
  const timePopoverRef = useRef<HTMLDivElement>(null)
  const openedDeepLinkTaskIdRef = useRef<string | null>(null)
  const closeDeliveryConfirm = useCallback(() => setPendingDelivery(null), [])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const discardTimeDraft = useCallback(() => {
    setDraftRange(dateRange); setDateError(''); setIsTimeOpen(false); timeTriggerRef.current?.focus()
  }, [dateRange])
  const load = useCallback(async (page = currentPage) => {
    setIsLoading(true)
    try {
      const result = await getTaskCenterTasks({ statuses: statusFilters, submittedFrom: dateRange.start, submittedTo: dateRange.end, page, pageSize })
      if (page > 1 && result.total > 0 && result.items.length === 0) {
        setCurrentPage(Math.max(1, Math.ceil(result.total / pageSize)))
        return
      }
      setTasks(result.items)
      setTotal(result.total)
    } catch (error) {
      showToast(errorMessage(error, '任务列表加载失败，请稍后重试。'))
      setTasks([])
      setTotal(0)
    } finally { setIsLoading(false) }
  }, [currentPage, dateRange.end, dateRange.start, showToast, statusFilters])

  useEffect(() => {
    const scheduledLoad = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(scheduledLoad)
  }, [load])
  useEffect(() => () => {
    if (pendingDelivery) URL.revokeObjectURL(pendingDelivery.previewUrl)
  }, [pendingDelivery])
  useEffect(() => {
    const closeOnOutside = (event: MouseEvent) => {
      if (isTimeOpen && !timePopoverRef.current?.contains(event.target as Node) && !timeTriggerRef.current?.contains(event.target as Node)) discardTimeDraft()
    }
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && isTimeOpen) discardTimeDraft() }
    document.addEventListener('mousedown', closeOnOutside); document.addEventListener('keydown', closeOnEscape)
    return () => { document.removeEventListener('mousedown', closeOnOutside); document.removeEventListener('keydown', closeOnEscape) }
  }, [discardTimeDraft, isTimeOpen])
  const applyStatusSelection = (status: TaskCenterStatus | null) => {
    const next = status === null ? [] : statusFilters.includes(status) ? statusFilters.filter((item) => item !== status) : [...statusFilters, status]
    setStatusFilters(next); setCurrentPage(1)
  }
  const applyPreset = (preset: string) => {
    const today = new Date(); const end = localDate(today.toISOString()); const startDate = new Date(today)
    if (preset === 'seven') startDate.setDate(today.getDate() - 6)
    if (preset === 'thirty') startDate.setDate(today.getDate() - 29)
    const next = preset === 'all' ? { start: '', end: '' } : { start: localDate(startDate.toISOString()), end }
    setTimePreset(preset); setDateRange(next); setDraftRange(next); setDateError(''); setIsTimeOpen(false); setCurrentPage(1); timeTriggerRef.current?.focus()
  }
  const applyDates = () => {
    if (draftRange.start && draftRange.end && draftRange.start > draftRange.end) { setDateError('开始日期不能晚于结束日期'); return }
    setDateRange(draftRange); setTimePreset('custom'); setDateError(''); setIsTimeOpen(false); setCurrentPage(1); timeTriggerRef.current?.focus()
  }
  const clearFilters = () => { setStatusFilters([]); setTimePreset('all'); setDateRange({ start: '', end: '' }); setDraftRange({ start: '', end: '' }); setDateError(''); setCurrentPage(1) }
  const toggleTimePopover = () => { if (isTimeOpen) discardTimeDraft(); else { setDraftRange(dateRange); setDateError(''); setIsTimeOpen(true) } }
  const openTask = useCallback(async (taskId: string) => {
    if (busyTaskId) return
    setBusyTaskId(taskId)
    try {
      setSelectedTask(await getTaskCenterTask(taskId))
      openedDeepLinkTaskIdRef.current = taskId
    } catch (error) {
      showToast(errorMessage(error, '任务详情加载失败，请稍后重试。'))
    } finally {
      setBusyTaskId(null)
    }
  }, [busyTaskId, showToast])
  const deepLinkTaskId = searchParams.get('task_id')
  useEffect(() => {
    if (!deepLinkTaskId) {
      openedDeepLinkTaskIdRef.current = null
      return
    }
    if (openedDeepLinkTaskIdRef.current === deepLinkTaskId && selectedTask?.id === deepLinkTaskId) return
    if (busyTaskId) return
    void Promise.resolve().then(() => openTask(deepLinkTaskId))
  }, [busyTaskId, deepLinkTaskId, openTask, selectedTask?.id])
  const closeTaskDetail = () => {
    setSelectedTask(null)
    if (!searchParams.has('task_id')) return
    const next = new URLSearchParams(searchParams)
    next.delete('task_id')
    openedDeepLinkTaskIdRef.current = null
    setSearchParams(next, { replace: true })
  }
  const accept = async (taskId: string) => {
    if (busyTaskId) return
    const cachedTask = tasks.find((task) => task.id === taskId) ?? (selectedTask?.id === taskId ? selectedTask : null)
    const accessToast = cachedTask ? customerAccessToast(cachedTask.customer_access_status) : null
    if (accessToast) { showToast(accessToast); return }
    setBusyTaskId(taskId)
    try {
      const acceptedTask = await acceptTask(taskId)
      setSelectedTask((current) => current?.id === taskId ? { ...current, status: acceptedTask.status } : current)
      showToast('已接单，任务进入处理中')
      await load()
    } catch (error) {
      const serverAccessToast = customerAccessToast(errorCode(error) === 'customer_access_expired' ? 'expired' : errorCode(error) === 'customer_access_stopped' ? 'stopped' : 'active')
      if (serverAccessToast) showToast(serverAccessToast)
      else if (isTaskChanged(error)) { if (selectedTask?.id === taskId) closeTaskDetail(); setIsTaskChangedOpen(true) }
      else showToast(errorMessage(error, '接单失败，请稍后重试。'))
    } finally { setBusyTaskId(null) }
  }
  const prepareUpload = async (task: TaskCenterItem, file: File, fromDetail = false) => {
    if (busyTaskId || pendingDelivery) return
    const accessToast = customerAccessToast(task.customer_access_status)
    if (accessToast) { showToast(accessToast); return }
    try {
      await validateDeliveryImage(file)
      if (fromDetail) closeTaskDetail()
      setPendingDelivery({ task, file, previewUrl: URL.createObjectURL(file) })
    } catch (error) {
      showToast(errorMessage(error, '无法读取所选图片'))
    }
  }
  const upload = async () => {
    if (!pendingDelivery || busyTaskId) return
    const { task, file } = pendingDelivery
    setBusyTaskId(task.id)
    try {
      await uploadTaskDeliveryImage(task.id, file)
      setPendingDelivery(null)
      showToast('图片上传成功')
      await load()
    } catch (error) {
      const serverAccessToast = customerAccessToast(errorCode(error) === 'customer_access_expired' ? 'expired' : errorCode(error) === 'customer_access_stopped' ? 'stopped' : 'active')
      if (serverAccessToast) {
        URL.revokeObjectURL(pendingDelivery.previewUrl)
        setPendingDelivery(null)
        showToast(serverAccessToast)
      } else if (isTaskChanged(error)) {
        URL.revokeObjectURL(pendingDelivery.previewUrl)
        setPendingDelivery(null)
        setIsTaskChangedOpen(true)
      } else {
        showToast(errorMessage(error, '交付图片上传失败'))
      }
    } finally {
      setBusyTaskId(null)
    }
  }
  const exportTasks = async () => {
    if (isExporting) return
    setIsExporting(true)
    try { await downloadTaskExport({ statuses: statusFilters, submittedFrom: dateRange.start, submittedTo: dateRange.end }); showToast('任务表已导出') } catch (error) { showToast(errorMessage(error, '导出失败，请稍后重试。')) } finally { setIsExporting(false) }
  }
  const downloadSelectedImage = async (task: TaskCenterDetail) => {
    const safeDomain = task.domain.replace(/[^a-zA-Z0-9._-]+/g, '-') || 'logo'
    try { await downloadTaskImage(task.adopted_image_url, `${safeDomain}-selected-logo`) } catch (error) { showToast(errorMessage(error, '图片下载失败，请稍后重试。')) }
  }
  const timeLabel = timePreset === 'all' ? '全部时间' : timePreset === 'today' ? '当天' : timePreset === 'seven' ? '近7天' : timePreset === 'thirty' ? '近30天' : `${dateRange.start || '开始'} 至 ${dateRange.end || '结束'}`
  const isFiltered = statusFilters.length > 0 || timePreset !== 'all'
  const exportTitle = isFiltered ? '导出当前筛选条件下的全部任务（跨全部分页）' : '导出全部任务（跨全部分页）'
  const pageTokens = useMemo(() => paginationTokens(currentPage, totalPages), [currentPage, totalPages])

  return <div className="internal-shell"><AdminNavigation /><main className="task-center-page">
    <header className="task-center-toolbar"><div><h1>任务中心</h1><p>集中接单、交付并追踪每个采用方案。</p></div><button className="internal-button" type="button" disabled={isExporting} title={exportTitle} aria-label={exportTitle} onClick={() => void exportTasks()}>{isExporting ? '导出中...' : '导出 Excel'}</button></header>
    <div className="task-filter-bar"><div className="task-filter-status" role="group" aria-label="按状态筛选"><button type="button" className={!statusFilters.length ? 'active' : ''} aria-pressed={!statusFilters.length} onClick={() => applyStatusSelection(null)}>全部</button>{statusOptions.map((option) => <button type="button" className={statusFilters.includes(option.value) ? 'active' : ''} aria-pressed={statusFilters.includes(option.value)} onClick={() => applyStatusSelection(option.value)} key={option.value}>{option.label}</button>)}</div><span className="task-filter-divider" /><div className="task-time-filter"><button ref={timeTriggerRef} className="task-time-trigger" type="button" aria-haspopup="dialog" aria-expanded={isTimeOpen} onClick={toggleTimePopover}><CalendarDays size={16} /><span>{timeLabel}</span><ChevronDown size={16} /></button>{isTimeOpen && <div className="task-time-popover" ref={timePopoverRef} role="dialog" aria-label="按提交时间筛选"><div className="task-time-presets">{[['all', '全部时间'], ['today', '当天'], ['seven', '近7天'], ['thirty', '近30天']].map(([preset, name]) => <button type="button" key={preset} onClick={() => applyPreset(preset)}>{name}</button>)}</div><div className="task-date-fields"><label>开始<input type="date" value={draftRange.start} onChange={(event) => setDraftRange({ ...draftRange, start: event.target.value })} /></label><label>结束<input type="date" value={draftRange.end} onChange={(event) => setDraftRange({ ...draftRange, end: event.target.value })} /></label></div>{dateError && <p className="task-date-error">{dateError}</p>}<div className="task-time-actions"><button type="button" onClick={discardTimeDraft}>取消</button><button type="button" className="primary" onClick={applyDates}>应用</button></div></div>}</div>{isFiltered && <button className="task-clear-filter" type="button" onClick={clearFilters}><RotateCcw size={14} />清除筛选</button>}</div>
    <section className="task-center-list"><header><div><h2>全部任务</h2><p>按提交时间倒序。上传 PNG/JPEG 交付图后，任务自动标记为已完成。</p></div></header><div className="task-center-table-wrap"><table className="task-center-table"><thead><tr><th>客户名称</th><th>域名</th><th>提交时间</th><th>状态</th><th>精修建议</th><th>操作</th></tr></thead><tbody>{tasks.map((task) => <tr key={task.id}><td>{task.customer_name}</td><td><b>{task.domain}</b></td><td className="task-submitted-at"><time dateTime={task.submitted_at}>{formatBeijingDateTime(task.submitted_at)}</time></td><td><span className={`task-center-status ${task.status}`}>{labels[task.status]}</span></td><td>{empty(task.adoption_suggestion)}</td><td><div className="task-center-actions">{task.status === 'waiting_assignment' && <button className="task-accept-button" type="button" disabled={busyTaskId === task.id} onClick={() => void accept(task.id)}>{busyTaskId === task.id ? '处理中...' : '接单'}</button>}{task.status === 'in_progress' && <label className="task-delivery-label">{busyTaskId === task.id ? '上传中...' : '上传图片'}<input className="sr-only" type="file" disabled={busyTaskId === task.id} accept="image/png,image/jpeg,.png,.jpg,.jpeg" onChange={(event) => { const file = event.target.files?.[0]; event.currentTarget.value = ''; if (file) void prepareUpload(task, file) }} /></label>}<button className="internal-button" type="button" disabled={busyTaskId === task.id} onClick={() => void openTask(task.id)}>{busyTaskId === task.id ? '加载中...' : '查看详情'}</button></div></td></tr>)}</tbody></table>{!isLoading && tasks.length === 0 && <p className="task-center-empty">没有符合当前筛选条件的任务</p>}{isLoading && <p className="task-center-empty">正在加载任务...</p>}</div><nav className="task-pagination" aria-label="任务列表分页"><span className="task-pagination-summary" aria-live="polite"><span>{pageSize} 条/页</span><span>共 {total} 条</span></span><div className="task-pagination-controls"><button className="task-pagination-icon" type="button" aria-label="上一页" title="上一页" disabled={currentPage === 1 || isLoading} onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}><ChevronLeft size={16} aria-hidden="true" /></button>{pageTokens.map((token) => typeof token === 'number' ? <button className={`task-pagination-page${token === currentPage ? ' active' : ''}`} type="button" key={token} disabled={isLoading} aria-label={`第 ${token} 页`} aria-current={token === currentPage ? 'page' : undefined} title={`第 ${token} 页`} onClick={() => setCurrentPage(token)}>{token}</button> : <span className="task-pagination-ellipsis" aria-hidden="true" key={token}>...</span>)}<button className="task-pagination-icon" type="button" aria-label="下一页" title="下一页" disabled={currentPage === totalPages || isLoading} onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}><ChevronRight size={16} aria-hidden="true" /></button></div></nav></section>
    {selectedTask && <TaskDetailModal task={selectedTask} isBusy={busyTaskId === selectedTask.id} onAccept={() => void accept(selectedTask.id)} onClose={closeTaskDetail} onDownload={() => downloadSelectedImage(selectedTask)} onUpload={(file) => void prepareUpload(selectedTask, file, true)} />}
    {pendingDelivery && <DeliveryConfirmModal pending={pendingDelivery} isUploading={busyTaskId === pendingDelivery.task.id} onCancel={closeDeliveryConfirm} onConfirm={() => void upload()} />}
    {isTaskChangedOpen && <TaskChangedModal onCancel={() => setIsTaskChangedOpen(false)} onRefresh={() => window.location.reload()} />}
    <GlobalToast />
  </main></div>
}
