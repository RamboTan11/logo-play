import { api } from './api'

export type TaskCenterStatus = 'waiting_assignment' | 'in_progress' | 'completed' | 'canceled'
export type CustomerAccessStatus = 'unstarted' | 'active' | 'stopped' | 'expired'

export interface TaskCenterItem {
  id: string
  customer_name: string
  domain: string
  status: TaskCenterStatus
  adoption_suggestion: string | null
  submitted_at: string
  customer_access_status: CustomerAccessStatus
}

export interface TaskCenterDetail extends TaskCenterItem {
  adopted_image_url: string
  delivery_image_url: string | null
}

interface ApiResponse<T> { data: T }
interface TaskListData { items: TaskCenterItem[]; total: number; page: number; page_size: number }
interface TaskDetailData { task: TaskCenterDetail }
interface TaskMutationData { task: TaskCenterItem }

export interface TaskCenterFilters {
  statuses: TaskCenterStatus[]
  submittedFrom: string
  submittedTo: string
  page: number
  pageSize: number
}

function searchParams(filters: Omit<TaskCenterFilters, 'page' | 'pageSize'> & Partial<Pick<TaskCenterFilters, 'page' | 'pageSize'>>): URLSearchParams {
  const params = new URLSearchParams()
  filters.statuses.forEach((status) => params.append('status', status))
  if (filters.submittedFrom) params.set('submitted_from', filters.submittedFrom)
  if (filters.submittedTo) params.set('submitted_to', filters.submittedTo)
  if (filters.page) params.set('page', String(filters.page))
  if (filters.pageSize) params.set('page_size', String(filters.pageSize))
  return params
}

export async function getTaskCenterTasks(filters: TaskCenterFilters): Promise<TaskListData> {
  const response = await api.get<ApiResponse<TaskListData>>('/v1/design-tasks', { params: searchParams(filters) })
  return response.data.data
}

export async function getTaskCenterTask(taskId: string): Promise<TaskCenterDetail> {
  const response = await api.get<ApiResponse<TaskDetailData>>(`/v1/design-tasks/${encodeURIComponent(taskId)}`)
  return response.data.data.task
}

export async function acceptTask(taskId: string): Promise<TaskCenterItem> {
  const response = await api.post<ApiResponse<TaskMutationData>>(`/v1/design-tasks/${encodeURIComponent(taskId)}/accept`)
  return response.data.data.task
}

export async function uploadTaskDeliveryImage(taskId: string, image: File): Promise<TaskCenterItem> {
  await validateDeliveryImage(image)
  const form = new FormData()
  form.append('image', image)
  const response = await api.post<ApiResponse<TaskMutationData>>(
    `/v1/design-tasks/${encodeURIComponent(taskId)}/delivery-image`,
    form,
  )
  return response.data.data.task
}

export async function downloadTaskExport(filters: Omit<TaskCenterFilters, 'page' | 'pageSize'>): Promise<void> {
  const response = await api.get('/v1/design-tasks/export', {
    params: searchParams(filters),
    responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data as Blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = '任务中心导出.xlsx'
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function downloadTaskImage(imageUrl: string, filenameStem: string): Promise<void> {
  const response = await fetch(imageUrl, { credentials: 'include' })
  if (!response.ok) throw new Error('图片下载失败，请稍后重试。')
  const blob = await response.blob()
  const extension = blob.type === 'image/png' ? 'png' : blob.type === 'image/jpeg' ? 'jpg' : 'image'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${filenameStem}.${extension}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export async function validateDeliveryImage(file: File): Promise<void> {
  const suffix = file.name.toLowerCase().split('.').pop()
  const expectedType = suffix === 'png' ? 'image/png' : suffix === 'jpg' || suffix === 'jpeg' ? 'image/jpeg' : null
  if (!expectedType) throw new Error('仅支持 PNG 或 JPEG 图片')
  if (file.type !== expectedType) throw new Error('图片格式与文件扩展名不一致')
  if (file.size === 0 || file.size > 10 * 1024 * 1024) throw new Error('图片大小不能超过 10 MB')
  const bytes = new Uint8Array(await file.arrayBuffer())
  const isPng = bytes.length >= 8 && bytes.slice(0, 8).every((value, index) => value === [137, 80, 78, 71, 13, 10, 26, 10][index])
  const isJpeg = bytes.length >= 4 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 && bytes.at(-2) === 255 && bytes.at(-1) === 217
  if ((expectedType === 'image/png' && !isPng) || (expectedType === 'image/jpeg' && !isJpeg)) throw new Error('图片内容无法验证')
}
