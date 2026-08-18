export type LarkSecretStatus = 'configured' | 'missing'
export type LarkDeliveryStatus = 'accepted' | 'retrying' | 'failed'
export type LarkNotificationMode = 'mention' | 'group_only'

export type LarkEventType =
  | 'task.adoption_submitted'
  | 'task.waiting_assignment_overdue'
  | 'task.upload_overdue'
  | 'task.adoption_changed_before_acceptance'
  | 'task.adoption_changed_in_progress'
  | 'task.delivery_uploaded'
  | 'task.customer_feedback_submitted'

export interface LarkChannelDto {
  enabled: boolean
  group_label: string | null
  webhook_status: LarkSecretStatus
  signing_enabled: boolean
  signing_secret_status: LarkSecretStatus
  last_test_status: LarkDeliveryStatus | null
  last_tested_at: string | null
  last_success_at: string | null
  updated_at: string | null
}

export interface LarkChannelPayload {
  enabled: boolean
  group_label: string | null
  webhook?: string
  signing_enabled: boolean
  signing_secret?: string
}

export interface LarkRecipientDto {
  id: string
  display_name: string | null
  open_id_masked: string
  enabled: boolean
  updated_at: string
}

export interface LarkRecipientCreatePayload {
  display_name: string | null
  open_id: string
  enabled: boolean
}

export interface LarkRecipientUpdatePayload {
  display_name?: string | null
  open_id?: string
  enabled?: boolean
}

export interface LarkNotificationRuleDto {
  event_type: LarkEventType
  enabled: boolean
  mention_all: boolean
  recipient_ids: string[]
  threshold_hours: number | null
  repeat_interval_hours: number | null
  max_repeat_count: number | null
  updated_at: string | null
}

export interface LarkNotificationRulePayload {
  enabled: boolean
  mention_all: boolean
  recipient_ids: string[]
  threshold_hours?: number
  repeat_interval_hours?: number
  max_repeat_count?: number
}

export interface LarkNotificationRuleBatchItem extends LarkNotificationRulePayload {
  event_type: LarkEventType
}

export interface LarkTestPayload {
  mention_enabled: boolean
  recipient_ids?: string[]
}

export interface LarkTestResult {
  accepted: boolean
  status: LarkDeliveryStatus
  tested_at: string
  trace_id: string
}

export interface LarkRecentDeliveryDto {
  id: string
  created_at: string
  event_type: string
  task_id: string | null
  task_url: string | null
  notification_mode: LarkNotificationMode
  reminder_index: number
  status: LarkDeliveryStatus
  error_summary: string | null
}

export type LarkDeliveryFilter = 'all' | 'retrying' | 'failed'
