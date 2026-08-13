import axios from 'axios'
import type { ApiResponse } from '../types/api'

export class CustomerDecisionApiError extends Error {
  constructor(readonly code: string, message: string) {
    super(message)
  }
}

const pendingKeys = new Map<string, string>()

function validationMessage(detail: unknown): string | null {
  if (!Array.isArray(detail) || !detail.length) return null
  const first = detail[0]
  if (!first || typeof first !== 'object') return null
  const record = first as { loc?: unknown; msg?: unknown }
  const field = Array.isArray(record.loc)
    ? record.loc.filter((part): part is string => typeof part === 'string' && part !== 'body').join('.')
    : ''
  const message = typeof record.msg === 'string' ? record.msg : ''
  if (!message) return null
  return field ? `${field}: ${message}` : message
}

export function idempotencyKey(fingerprint: string): string {
  const existing = pendingKeys.get(fingerprint)
  if (existing) return existing
  const key = crypto.randomUUID()
  pendingKeys.set(fingerprint, key)
  return key
}

export function releaseIdempotencyKey(fingerprint: string): void {
  pendingKeys.delete(fingerprint)
}

export function decisionError(error: unknown, fallbackCode: string, fallbackMessage: string): CustomerDecisionApiError {
  if (!axios.isAxiosError(error)) return new CustomerDecisionApiError(fallbackCode, fallbackMessage)
  const payload = error.response?.data as (ApiResponse<unknown> & { detail?: unknown }) | undefined
  const message = typeof payload?.message === 'string' && payload.message.trim() && payload.message !== 'Request validation failed'
    ? payload.message
    : validationMessage(payload?.detail) ?? fallbackMessage
  return new CustomerDecisionApiError(payload?.metadata?.error_code ?? fallbackCode, message)
}

export function hasServerResponse(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response !== undefined
}
