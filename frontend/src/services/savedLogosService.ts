import { getSavedLogosMock, saveLogoMock, updateSavedLogoMock } from '../mocks/generationsMock'
import type { ApiResponse, SaveLogoData, SavedLogoListItem, SavedLogosData } from '../types/api'
import { api } from './api'
import {
  decisionError,
  hasServerResponse,
  idempotencyKey,
  releaseIdempotencyKey,
} from './customerDecisionApi'

const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'

export async function saveLogo(logoVersionId: string, domain = 'LOGO'): Promise<SaveLogoData> {
  if (isMockMode) return (await saveLogoMock({ logo_version_id: logoVersionId }, domain)).data

  const fingerprint = `save:${logoVersionId}`
  try {
    const response = await api.post<ApiResponse<SaveLogoData>>(
      '/v1/saved-logos',
      { logo_version_id: logoVersionId },
      { headers: { 'Idempotency-Key': idempotencyKey(fingerprint) } },
    )
    releaseIdempotencyKey(fingerprint)
    return response.data.data
  } catch (error) {
    if (hasServerResponse(error)) releaseIdempotencyKey(fingerprint)
    throw decisionError(error, 'save_logo_failed', '收藏失败，请稍后重试。')
  }
}

export async function updateSavedLogo(savedLogoId: string, logoVersionId: string): Promise<SaveLogoData> {
  if (isMockMode) return (await updateSavedLogoMock(savedLogoId, logoVersionId)).data

  const fingerprint = `update-save:${savedLogoId}:${logoVersionId}`
  try {
    const response = await api.patch<ApiResponse<SaveLogoData>>(
      `/v1/saved-logos/${encodeURIComponent(savedLogoId)}`,
      { logo_version_id: logoVersionId },
      { headers: { 'Idempotency-Key': idempotencyKey(fingerprint) } },
    )
    releaseIdempotencyKey(fingerprint)
    return response.data.data
  } catch (error) {
    if (hasServerResponse(error)) releaseIdempotencyKey(fingerprint)
    throw decisionError(error, 'saved_logo_update_failed', '收藏方案更新失败，请稍后重试。')
  }
}

export async function getSavedLogos(): Promise<SavedLogoListItem[]> {
  try {
    if (isMockMode) return (await getSavedLogosMock()).data.items
    return (await api.get<ApiResponse<SavedLogosData>>('/v1/saved-logos')).data.data.items
  } catch (error) {
    throw decisionError(error, 'saved_logos_load_failed', '收藏方案加载失败，请稍后重试。')
  }
}
