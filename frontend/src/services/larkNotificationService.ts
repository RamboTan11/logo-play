import type { ApiResponse } from '../types/api'
import type {
  LarkChannelDto,
  LarkChannelPayload,
  LarkDeliveryFilter,
  LarkNotificationRuleDto,
  LarkNotificationRuleBatchItem,
  LarkRecentDeliveryDto,
  LarkRecipientCreatePayload,
  LarkRecipientDto,
  LarkRecipientUpdatePayload,
  LarkTestPayload,
  LarkTestResult,
} from '../types/larkNotification'
import { api } from './api'

export async function getLarkChannel(): Promise<LarkChannelDto> {
  const response = await api.get<ApiResponse<LarkChannelDto>>('/v1/notification-channels/lark')
  return response.data.data
}

export async function updateLarkChannel(payload: LarkChannelPayload): Promise<LarkChannelDto> {
  const response = await api.put<ApiResponse<LarkChannelDto>>('/v1/notification-channels/lark', payload)
  return response.data.data
}

export async function sendLarkTest(payload: LarkTestPayload): Promise<LarkTestResult> {
  const response = await api.post<ApiResponse<LarkTestResult>>('/v1/notification-channels/lark/test', payload)
  return response.data.data
}

export async function getLarkRecipients(): Promise<LarkRecipientDto[]> {
  const response = await api.get<ApiResponse<LarkRecipientDto[]>>('/v1/notification-recipients/lark')
  return response.data.data
}

export async function createLarkRecipient(payload: LarkRecipientCreatePayload): Promise<LarkRecipientDto> {
  const response = await api.post<ApiResponse<LarkRecipientDto>>('/v1/notification-recipients/lark', payload)
  return response.data.data
}

export async function updateLarkRecipient(recipientId: string, payload: LarkRecipientUpdatePayload): Promise<LarkRecipientDto> {
  const response = await api.patch<ApiResponse<LarkRecipientDto>>(`/v1/notification-recipients/lark/${encodeURIComponent(recipientId)}`, payload)
  return response.data.data
}

export async function deleteLarkRecipient(recipientId: string): Promise<void> {
  await api.delete<ApiResponse<{ deleted: true }>>(`/v1/notification-recipients/lark/${encodeURIComponent(recipientId)}`)
}

export async function getLarkRules(): Promise<LarkNotificationRuleDto[]> {
  const response = await api.get<ApiResponse<LarkNotificationRuleDto[]>>('/v1/notification-rules/lark')
  return response.data.data
}

export async function updateLarkRules(rules: LarkNotificationRuleBatchItem[]): Promise<LarkNotificationRuleDto[]> {
  const response = await api.put<ApiResponse<LarkNotificationRuleDto[]>>('/v1/notification-rules/lark', { rules })
  return response.data.data
}

export async function getRecentLarkDeliveries(status: LarkDeliveryFilter): Promise<LarkRecentDeliveryDto[]> {
  const response = await api.get<ApiResponse<{ items: LarkRecentDeliveryDto[] }>>('/v1/notification-deliveries/lark/recent', {
    params: { status, limit: 10 },
  })
  return response.data.data.items
}
