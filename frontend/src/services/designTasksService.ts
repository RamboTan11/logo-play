import { adoptLogoMock, getMyTaskMock, getMyTasksMock } from '../mocks/generationsMock'
import type {
  AdoptLogoData,
  ApiResponse,
  MyTaskDetail,
  MyTaskDetailData,
  MyTaskListItem,
  MyTasksData,
} from '../types/api'
import { api } from './api'
import {
  CustomerDecisionApiError,
  decisionError,
  hasServerResponse,
  idempotencyKey,
  releaseIdempotencyKey,
} from './customerDecisionApi'

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'

export type AdoptionResult = 'adopted' | 'updated' | 'completed_task_exists' | 'active_task_confirmation_required'

export async function adoptLogo(
  logoVersionId: string,
  adoptionSuggestion: string | null,
  mockContext?: { domain: string; initialLogoVersionId: string; aiEditInputs: string[] },
  confirmReplaceActiveTask = false,
): Promise<AdoptionResult> {
  if (isMockMode) {
    const response = await adoptLogoMock(
      {
        logo_version_id: logoVersionId,
        adoption_suggestion: adoptionSuggestion,
        confirm_replace_active_task: confirmReplaceActiveTask,
      },
      mockContext ?? { domain: 'LOGO', initialLogoVersionId: logoVersionId, aiEditInputs: [] },
    )
    if (response.code === 409 && response.message === 'active_task_confirmation_required') {
      return 'active_task_confirmation_required'
    }
    if (response.code === 409) return 'completed_task_exists'
    return response.data.created ? 'adopted' : 'updated'
  }

  const normalizedSuggestion = adoptionSuggestion?.trim() || null
  const fingerprint = `adopt:${logoVersionId}:${normalizedSuggestion ?? ''}:${confirmReplaceActiveTask}`
  try {
    const response = await api.post<ApiResponse<AdoptLogoData>>(
      '/v1/design-tasks/adopt',
      {
        logo_version_id: logoVersionId,
        adoption_suggestion: normalizedSuggestion,
        confirm_replace_active_task: confirmReplaceActiveTask,
      },
      { headers: { 'Idempotency-Key': idempotencyKey(fingerprint) } },
    )
    releaseIdempotencyKey(fingerprint)
    return response.data.data.created ? 'adopted' : 'updated'
  } catch (error) {
    if (hasServerResponse(error)) releaseIdempotencyKey(fingerprint)
    const failure = decisionError(error, 'adoption_failed', '采用失败，请稍后重试。')
    if (failure.code === 'completed_task_exists') return 'completed_task_exists'
    if (failure.code === 'active_task_confirmation_required') return 'active_task_confirmation_required'
    throw failure
  }
}

export async function getMyTasks(): Promise<MyTaskListItem[]> {
  try {
    if (isMockMode) return (await getMyTasksMock()).data.items
    return (await api.get<ApiResponse<MyTasksData>>('/v1/my/tasks')).data.data.items
  } catch (error) {
    throw decisionError(error, 'tasks_load_failed', '方案列表加载失败，请稍后重试。')
  }
}

export async function getMyTask(taskId: string): Promise<MyTaskDetail> {
  try {
    if (isMockMode) return (await getMyTaskMock(taskId)).data.task
    return (await api.get<ApiResponse<MyTaskDetailData>>(`/v1/my/tasks/${encodeURIComponent(taskId)}`)).data.data.task
  } catch (error) {
    const failure = decisionError(error, 'task_load_failed', '方案详情加载失败，请稍后重试。')
    if (failure.code === 'task_not_found') throw new CustomerDecisionApiError('task_not_found', '未找到该任务')
    throw failure
  }
}
