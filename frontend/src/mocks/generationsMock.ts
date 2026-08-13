import type {
  AdoptLogoData,
  AdoptLogoRequest,
  ApiResponse,
  BatchGenerationData,
  BatchGenerationRequest,
  GenerationStatusData,
  GenerationCandidateSlot,
  GenerationSlotRetryData,
  MyTaskDetailData,
  MyTasksData,
  SaveLogoData,
  SaveLogoRequest,
  SavedLogosData,
  SingleEditGenerationData,
  SingleEditGenerationRequest,
} from '../types/api'
import { getActiveBatchGenerationTargetCountMock } from './modelStrategyMock'

const mockCompletionDelayMs = 1200
let batchSequence = 0
const mockTaskStorageKey = 'logo-generated.mock-design-tasks'
const mockTaskSeedVersionKey = 'logo-generated.mock-design-tasks-seed-version'
const mockTaskSeedVersion = 't031-my-plans-v1'
const mockSavedLogoStorageKey = 'logo-generated.mock-saved-logos'
const mockCustomerId = 'mock-customer-001'
const mockBatchSlots = new Map<string, GenerationCandidateSlot[]>()
const mockRetryKeys = new Set<string>()


type MockTaskStatus = 'waiting_assignment' | 'in_progress' | 'completed' | 'canceled'

interface MockDesignTask {
  id: string
  customer_id: string
  domain: string
  status: MockTaskStatus
  submitted_at: string
  updated_at: string
  adopted_logo_version_id: string
  initial_single_edit_version_id: string
  ai_edit_inputs: string[]
  adoption_suggestion: string | null
  delivery_image: { filename: string; media_type: 'image/png' | 'image/jpeg' } | null
  delivery_uploaded_at: string | null
}

interface MockSavedLogo {
  id: string
  logo_version_id: string
  domain: string
  saved_at: string
}

interface MockAdoptionContext {
  domain: string
  initialLogoVersionId: string
  aiEditInputs: string[]
}

export interface MockTaskCenterItem extends MockDesignTask {
  customer_name: string
  delivery_image_url: string | null
}

const mockDeliveryPreviewUrls = new Map<string, string>()
const seededDeliveryImage = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL9WQAAAABJRU5ErkJggg=='

export class MockDeliveryImageError extends Error {}

const mockPrimaryTasks: MockDesignTask[] = [
  {
    id: 'mock-task-waiting', customer_id: mockCustomerId, domain: 'aurora-play.com', status: 'waiting_assignment',
    submitted_at: '2026-07-29T02:00:00.000Z', updated_at: '2026-07-29T02:00:00.000Z', adopted_logo_version_id: 'seed-aurora-v1',
    initial_single_edit_version_id: 'seed-aurora-v1', ai_edit_inputs: [], adoption_suggestion: null, delivery_image: null,
    delivery_uploaded_at: null,
  },
  {
    id: 'mock-task-progress', customer_id: mockCustomerId, domain: 'coastline.dev', status: 'in_progress',
    submitted_at: '2026-07-29T01:30:00.000Z', updated_at: '2026-07-29T03:10:00.000Z', adopted_logo_version_id: 'seed-coastline-v2',
    initial_single_edit_version_id: 'seed-coastline-v1', ai_edit_inputs: ['让图形更简洁，增强科技感'], adoption_suggestion: '保留简洁的几何关系。', delivery_image: null,
    delivery_uploaded_at: null,
  },
  {
    id: 'mock-task-completed', customer_id: mockCustomerId, domain: 'northstar.studio', status: 'completed',
    submitted_at: '2026-07-28T09:00:00.000Z', updated_at: '2026-07-28T12:20:00.000Z', adopted_logo_version_id: 'seed-northstar-v2',
    initial_single_edit_version_id: 'seed-northstar-v1', ai_edit_inputs: [], adoption_suggestion: null, delivery_image: { filename: 'northstar-logo-delivery.png', media_type: 'image/png' },
    delivery_uploaded_at: '2026-07-28T12:20:00.000Z',
  },
]

const mockTaskCenterBoundaryTasks: MockDesignTask[] = Array.from({ length: 28 }, (_, index) => {
  const sequence = String(index + 1).padStart(2, '0')
  const submittedAt = new Date(Date.UTC(2026, 6, 27 - index, 8 + (index % 8), 0, 0)).toISOString()
  const status: MockTaskStatus = index < 15
    ? 'waiting_assignment'
    : index < 24
      ? 'in_progress'
      : 'completed'

  return {
    id: `mock-admin-task-${sequence}`,
    customer_id: `mock-customer-${String(index + 2).padStart(3, '0')}`,
    domain: `brand-${sequence}.example`,
    status,
    submitted_at: submittedAt,
    updated_at: submittedAt,
    adopted_logo_version_id: `mock-admin-${sequence}-v2`,
    initial_single_edit_version_id: `mock-admin-${sequence}-v1`,
    ai_edit_inputs: index % 4 === 0 ? ['强化图形识别度'] : [],
    adoption_suggestion: index % 2 === 0 ? `精简方案 ${sequence} 的细节。` : null,
    delivery_image: status === 'completed' ? { filename: `brand-${sequence}-delivery.jpg`, media_type: 'image/jpeg' } : null,
    delivery_uploaded_at: status === 'completed' ? submittedAt : null,
  }
})

const mockSeedTasks: MockDesignTask[] = [...mockPrimaryTasks, ...mockTaskCenterBoundaryTasks]

function normalizeDomain(domain: string): string {
  const candidate = domain.trim().toLowerCase()
  try {
    return new URL(candidate.includes('://') ? candidate : `https://${candidate}`).hostname
  } catch {
    return candidate.replace(/^https?:\/\//, '').split('/')[0]
  }
}

function isMockDesignTask(value: unknown): value is MockDesignTask {
  return typeof value === 'object'
    && value !== null
    && 'id' in value
    && 'customer_id' in value
    && 'domain' in value
    && 'status' in value
    && 'submitted_at' in value
    && 'updated_at' in value
    && typeof value.id === 'string'
    && typeof value.customer_id === 'string'
    && typeof value.domain === 'string'
    && ['waiting_assignment', 'in_progress', 'completed', 'canceled'].includes(String(value.status))
    && typeof value.submitted_at === 'string'
    && typeof value.updated_at === 'string'
}

function readMockTasks(): MockDesignTask[] {
  try {
    const stored = window.localStorage.getItem(mockTaskStorageKey)
    if (stored === null) {
      writeMockTasks(mockSeedTasks)
      window.localStorage.setItem(mockTaskSeedVersionKey, mockTaskSeedVersion)
      return mockSeedTasks.map((task) => ({ ...task, ai_edit_inputs: [...task.ai_edit_inputs] }))
    }
    const parsed: unknown = JSON.parse(stored)
    const storedTasks = Array.isArray(parsed) ? parsed.filter(isMockDesignTask) : []
    if (window.localStorage.getItem(mockTaskSeedVersionKey) === mockTaskSeedVersion) return storedTasks

    const migratedTasks = mockSeedTasks.map((task) => ({ ...task, ai_edit_inputs: [...task.ai_edit_inputs] }))
    writeMockTasks(migratedTasks)
    window.localStorage.setItem(mockTaskSeedVersionKey, mockTaskSeedVersion)
    return migratedTasks
  } catch {
    window.localStorage.removeItem(mockTaskStorageKey)
    window.localStorage.removeItem(mockTaskSeedVersionKey)
    return []
  }
}

function readMockSavedLogos(): MockSavedLogo[] {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(mockSavedLogoStorageKey) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((value): value is Pick<MockSavedLogo, 'logo_version_id' | 'domain'> => typeof value === 'object'
      && value !== null
      && 'logo_version_id' in value
      && 'domain' in value
      && typeof value.logo_version_id === 'string'
      && typeof value.domain === 'string')
      .map((value) => ({
        id: 'id' in value && typeof value.id === 'string' ? value.id : `mock-saved-${value.logo_version_id}`,
        logo_version_id: value.logo_version_id,
        domain: value.domain,
        saved_at: 'saved_at' in value && typeof value.saved_at === 'string' ? value.saved_at : new Date().toISOString(),
      }))
  } catch {
    window.localStorage.removeItem(mockSavedLogoStorageKey)
    return []
  }
}

function writeMockSavedLogos(savedLogos: MockSavedLogo[]): void {
  window.localStorage.setItem(mockSavedLogoStorageKey, JSON.stringify(savedLogos))
}

function writeMockTasks(tasks: MockDesignTask[]): void {
  window.localStorage.setItem(mockTaskStorageKey, JSON.stringify(tasks))
}

function deliveryImageUrl(task: MockDesignTask): string | null {
  if (!task.delivery_image) return null
  return mockDeliveryPreviewUrls.get(task.id) ?? seededDeliveryImage
}

export async function createBatchGenerationMock(
  request: BatchGenerationRequest,
): Promise<ApiResponse<BatchGenerationData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 240))
  const domain = normalizeDomain(`${request.domain_label.trim()}${request.domain_suffix}`)
  if (readMockTasks().some((task) => task.customer_id === mockCustomerId && task.domain === domain && task.status === 'completed')) {
    return { code: 409, message: 'completed_task_exists', data: {} as BatchGenerationData }
  }
  batchSequence += 1
  const requestId = `mock-${request.domain_label.toLowerCase().replace(/[^a-z0-9]/g, '-') || 'generation'}-${Date.now()}-${batchSequence}`
  const targetCount = getActiveBatchGenerationTargetCountMock()
  mockBatchSlots.set(requestId, Array.from({ length: targetCount }, (_, slotIndex) => ({
    slot_index: slotIndex,
    status: slotIndex === 2 ? 'failed' : 'succeeded',
    logo_version_id: slotIndex === 2 ? null : `${requestId}-v${slotIndex + 1}`,
    image_url: slotIndex === 2 ? null : seededDeliveryImage,
    failure: slotIndex === 2
      ? { code: 'mock_slot_failed', message: '此方案生成失败，请重试。' }
      : null,
    retry_token: slotIndex === 2 ? `mock-retry-token-${requestId}-${slotIndex}` : null,
  })))



  return {
    code: 0,
    message: '已受理批量生成请求',
    data: {
      request_id: requestId,
      target_count: targetCount,
      created_candidate_jobs: targetCount,
      status: 'processing',
    },
  }
}

export async function createSingleEditGenerationMock(
  request: SingleEditGenerationRequest,
): Promise<ApiResponse<SingleEditGenerationData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 180))
  return {
    code: 0,
    message: '已受理单图生成请求',
    data: {
      request_id: `mock-edit-${request.source_version_id}-${Date.now()}`,
      source_version_id: request.source_version_id,
      status: 'processing',
    },
  }
}

export async function saveLogoMock(
  request: SaveLogoRequest,
  domain: string,
): Promise<ApiResponse<SaveLogoData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 100))
  const savedLogos = readMockSavedLogos()
  const existing = savedLogos.find((logo) => logo.logo_version_id === request.logo_version_id)
  const savedLogo = existing ?? {
    id: `mock-saved-${request.logo_version_id}`,
    logo_version_id: request.logo_version_id,
    domain: normalizeDomain(domain),
    saved_at: new Date().toISOString(),
  }
  if (!existing) writeMockSavedLogos([...savedLogos, savedLogo])
  return {
    code: existing ? 200 : 201,
    message: '已收藏方案',
    data: { saved_logo: { ...savedLogo, image_url: seededDeliveryImage }, created: existing === undefined },
  }
}

export async function getSavedLogosMock(): Promise<ApiResponse<SavedLogosData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 80))
  const items = readMockSavedLogos().map((logo) => ({ ...logo, image_url: seededDeliveryImage }))
  return { code: 0, message: 'ok', data: { items, total: items.length } }
}

export async function getMyTasksMock(): Promise<ApiResponse<MyTasksData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 80))
  const items = readMockTasks()
    .filter((task) => task.customer_id === mockCustomerId)
    .sort((left, right) => right.submitted_at.localeCompare(left.submitted_at))
    .map((task) => ({
      id: task.id,
      domain: task.domain,
      status: task.status,
      submitted_at: task.submitted_at,
      adoption_suggestion: task.adoption_suggestion,
      adopted_logo_version_id: task.adopted_logo_version_id,
      adopted_image_url: seededDeliveryImage,
      delivery_image_url: deliveryImageUrl(task),
      delivery_uploaded_at: task.delivery_uploaded_at,
    }))
  return { code: 0, message: 'ok', data: { items, total: items.length } }
}

export async function getMyTaskMock(taskId: string): Promise<ApiResponse<MyTaskDetailData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 80))
  const task = readMockTasks().find((item) => item.customer_id === mockCustomerId && item.id === taskId)
  if (!task) throw new Error('task_not_found')
  return {
    code: 0,
    message: 'ok',
    data: {
      task: {
        id: task.id,
        domain: task.domain,
        status: task.status,
        adoption_suggestion: task.adoption_suggestion,
        submitted_at: task.submitted_at,
        adopted_logo_version_id: task.adopted_logo_version_id,
        adopted_image_url: seededDeliveryImage,
        initial_logo_version_id: task.initial_single_edit_version_id,
        initial_image_url: seededDeliveryImage,
        ai_edit_inputs: [...task.ai_edit_inputs],
        delivery_image_url: deliveryImageUrl(task),
        delivery_uploaded_at: task.delivery_uploaded_at,
      },
    },
  }
}

export async function getTaskCenterTasksMock(): Promise<MockTaskCenterItem[]> {
  await new Promise((resolve) => window.setTimeout(resolve, 80))
  return readMockTasks()
    .sort((left, right) => right.submitted_at.localeCompare(left.submitted_at))
    .map((task) => ({ ...task, ai_edit_inputs: [...task.ai_edit_inputs], customer_name: '演示客户', delivery_image_url: deliveryImageUrl(task) }))
}

export async function acceptMockTask(taskId: string): Promise<MockTaskCenterItem | null> {
  await new Promise((resolve) => window.setTimeout(resolve, 100))
  const tasks = readMockTasks()
  const task = tasks.find((item) => item.id === taskId)
  if (!task || task.status !== 'waiting_assignment') return null
  const updated = { ...task, status: 'in_progress' as const, updated_at: new Date().toISOString() }
  writeMockTasks(tasks.map((item) => item.id === taskId ? updated : item))
  return { ...updated, ai_edit_inputs: [...updated.ai_edit_inputs], customer_name: '演示客户', delivery_image_url: deliveryImageUrl(updated) }
}

export async function uploadMockTaskImage(taskId: string, file: File): Promise<MockTaskCenterItem | null> {
  await new Promise((resolve) => window.setTimeout(resolve, 120))
  const mediaType = await validateDeliveryImage(file)
  const tasks = readMockTasks()
  const task = tasks.find((item) => item.id === taskId)
  if (!task || task.status !== 'in_progress') return null
  const oldPreview = mockDeliveryPreviewUrls.get(taskId)
  if (oldPreview) URL.revokeObjectURL(oldPreview)
  mockDeliveryPreviewUrls.set(taskId, URL.createObjectURL(file))
  const uploadedAt = new Date().toISOString()
  const updated = { ...task, status: 'completed' as const, delivery_image: { filename: file.name, media_type: mediaType }, delivery_uploaded_at: uploadedAt, updated_at: uploadedAt }
  writeMockTasks(tasks.map((item) => item.id === taskId ? updated : item))
  return { ...updated, ai_edit_inputs: [...updated.ai_edit_inputs], customer_name: '演示客户', delivery_image_url: deliveryImageUrl(updated) }
}

async function validateDeliveryImage(file: File): Promise<'image/png' | 'image/jpeg'> {
  if (file.size > 10 * 1024 * 1024) throw new MockDeliveryImageError('图片不能超过 10 MB')
  const extension = file.name.split('.').pop()?.toLowerCase()
  const expectedType = extension === 'png' ? 'image/png' : extension === 'jpg' || extension === 'jpeg' ? 'image/jpeg' : null
  if (!expectedType || file.type !== expectedType) throw new MockDeliveryImageError('仅支持 PNG、JPG 或 JPEG 图片')
  const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  const isPng = bytes.length >= 8 && [137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)
  const isJpeg = bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255
  if ((expectedType === 'image/png' && !isPng) || (expectedType === 'image/jpeg' && !isJpeg)) {
    throw new MockDeliveryImageError('图片内容与文件格式不一致')
  }
  return expectedType
}

export async function adoptLogoMock(
  request: AdoptLogoRequest,
  context: MockAdoptionContext,
): Promise<ApiResponse<AdoptLogoData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 100))
  const domain = normalizeDomain(context.domain)
  const tasks = readMockTasks()
  const customerTasks = tasks.filter((task) => task.customer_id === mockCustomerId)
  const completed = customerTasks.find((task) => task.status === 'completed')
  const active = customerTasks.filter((task) => task.status === 'waiting_assignment' || task.status === 'in_progress')

  if (completed) {
    return { code: 409, message: 'completed_task_exists', data: {} as AdoptLogoData }
  }

  if (active.length > 0 && !request.confirm_replace_active_task) {
    return { code: 409, message: 'active_task_confirmation_required', data: {} as AdoptLogoData }
  }

  const snapshot = {
    adopted_logo_version_id: request.logo_version_id,
    initial_single_edit_version_id: context.initialLogoVersionId,
    ai_edit_inputs: [...context.aiEditInputs],
    adoption_suggestion: request.adoption_suggestion,
  }
  const submittedAt = new Date().toISOString()
  const taskId = `mock-task-${Date.now()}`
  const canceledTasks = tasks.map((task) => active.some((item) => item.id === task.id)
    ? { ...task, status: 'canceled' as const, updated_at: submittedAt }
    : task)
  writeMockTasks([...canceledTasks, {
    id: taskId,
    customer_id: mockCustomerId,
    domain,
    status: 'waiting_assignment',
    submitted_at: submittedAt,
    updated_at: submittedAt,
    delivery_uploaded_at: null,
    delivery_image: null,
    ...snapshot,
  }])
  return {
    code: 201,
    message: active.length > 0 ? '已变更采用方案' : '已采用方案',
    data: {
      task: { id: taskId, domain, status: 'waiting_assignment', adoption_suggestion: request.adoption_suggestion, submitted_at: submittedAt, adopted_logo_version_id: request.logo_version_id, adopted_image_url: seededDeliveryImage, delivery_image_url: null, delivery_uploaded_at: null },
      created: true,
    },
  }
}
export async function retryBatchGenerationSlotMock(
  requestId: string,
  slotIndex: number,
  retryToken: string,
  idempotencyKey: string,
): Promise<ApiResponse<GenerationSlotRetryData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 120))
  const key = `${requestId}:${slotIndex}:${idempotencyKey}`
  const slots = mockBatchSlots.get(requestId) ?? []
  const slot = slots.find((candidate) => candidate.slot_index === slotIndex)
  if (!slot || slot.retry_token !== retryToken) throw new Error('invalid_retry_token')
  if (!mockRetryKeys.has(key)) {
    mockRetryKeys.add(key)
    Object.assign(slot, {
      status: 'succeeded',
      logo_version_id: `${requestId}-v${slotIndex + 1}-retry`,
      image_url: seededDeliveryImage,
      failure: null,
      retry_token: null,
    })
  }
  return {
    code: 202,
    message: 'Slot retry accepted',
    data: { request_id: requestId, slot_index: slotIndex, status: 'processing' },
  }
}



export async function getBatchGenerationStatusMock(
  _requestId: string,
  submittedAt: number,
): Promise<ApiResponse<GenerationStatusData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 120))
  const isComplete = Date.now() - submittedAt >= mockCompletionDelayMs

  return {
    code: 0,
    message: isComplete ? '批量生成已完成' : '批量生成处理中',
    data: { status: isComplete ? 'succeeded' : 'processing' },
  }
}
