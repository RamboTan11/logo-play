import axios from 'axios'
import { verifyAccessMock } from '../mocks/authMock'
import type { ApiResponse, AuthenticationStateData, LogoutData } from '../types/api'
import { notifyCustomerSessionInvalid } from '../utils/customerSession'
import { api } from './api'

export type AccessResult = 'valid' | 'invalid' | 'unstarted' | 'stopped' | 'expired' | 'unavailable'

const useMock = import.meta.env.VITE_USE_MOCK === 'true'

function errorCode(error: unknown): string | null {
  if (!axios.isAxiosError<ApiResponse<null>>(error)) return null
  return error.response?.data.metadata?.error_code ?? null
}

export async function verifyAccess(token: string): Promise<AccessResult> {
  if (useMock) {
    const response = await verifyAccessMock({ token })
    if (response.code === 0) return 'valid'
    return response.code === 403 ? 'stopped' : 'expired'
  }
  try {
    await api.post<ApiResponse<AuthenticationStateData>>('/v1/auth/verify', { token })
    return 'valid'
  } catch (error) {
    const code = errorCode(error)
    if (code === 'access_not_started') return 'unstarted'
    if (code === 'access_stopped') return 'stopped'
    if (code === 'access_expired') return 'expired'
    if (code === 'invalid_access_link') return 'invalid'
    return 'unavailable'
  }
}

export async function getCustomerSession(): Promise<boolean> {
  if (useMock) return window.localStorage.getItem('logo-generated.mock-access-authorized') === 'true'
  try {
    await api.get<ApiResponse<AuthenticationStateData>>('/v1/auth/session')
    return true
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 401) return false
    throw error
  }
}

export async function logoutCustomer(): Promise<void> {
  if (useMock) {
    window.localStorage.removeItem('logo-generated.mock-access-authorized')
    notifyCustomerSessionInvalid()
    return
  }
  await api.post<ApiResponse<LogoutData>>('/v1/auth/logout')
  notifyCustomerSessionInvalid()
}
