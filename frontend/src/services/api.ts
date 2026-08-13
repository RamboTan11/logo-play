import axios from 'axios'
import type { ApiResponse } from '../types/api'
import { notifyAdminSessionInvalid } from '../utils/adminSession'
import { notifyCustomerSessionInvalid } from '../utils/customerSession'

// Mock-only T-001 does not issue a real request; later integration tasks reuse this client.
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || `${import.meta.env.BASE_URL}api`,
  timeout: 10000,
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
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
