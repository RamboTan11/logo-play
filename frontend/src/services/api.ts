import axios from 'axios'
import type { ApiResponse } from '../types/api'
import { notifyAdminSessionInvalid } from '../utils/adminSession'
import { notifyCustomerSessionInvalid } from '../utils/customerSession'

function withPublicBaseForApiUrls(value: unknown): unknown {
  if (typeof value === 'string') {
    return value.startsWith('/api/')
      ? `${import.meta.env.BASE_URL}${value.slice(1)}`
      : value
  }
  if (Array.isArray(value)) return value.map(withPublicBaseForApiUrls)
  if (value === null || typeof value !== 'object') return value

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, nested]) => [
      key,
      withPublicBaseForApiUrls(nested),
    ]),
  )
}

// Mock-only T-001 does not issue a real request; later integration tasks reuse this client.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || `${import.meta.env.BASE_URL}api`,
  timeout: 10000,
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => {
    response.data = withPublicBaseForApiUrls(response.data)
    return response
  },
  (error: unknown) => {
    if (axios.isAxiosError<ApiResponse<unknown>>(error)
      && error.response?.status === 401
    ) {
      const errorCode = error.response.data?.metadata?.error_code
      if (errorCode === 'customer_session_required') notifyCustomerSessionInvalid()
      if (errorCode === 'admin_session_required') notifyAdminSessionInvalid()
    }
    return Promise.reject(error)
  },
)
