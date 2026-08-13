import type { ApiResponse, AuthenticationStateData, LogoutData } from '../types/api'
import { api } from './api'

const useMock = import.meta.env.VITE_USE_MOCK === 'true'

export async function loginAdmin(username: string, password: string): Promise<void> {
  if (useMock) return
  await api.post<ApiResponse<AuthenticationStateData>>('/v1/admin/auth/login', { username, password })
}

export async function getAdminSession(): Promise<boolean> {
  if (useMock) return true
  try {
    await api.get<ApiResponse<AuthenticationStateData>>('/v1/admin/auth/session')
    return true
  } catch {
    return false
  }
}

export async function logoutAdmin(): Promise<void> {
  if (useMock) return
  await api.post<ApiResponse<LogoutData>>('/v1/admin/auth/logout')
}
