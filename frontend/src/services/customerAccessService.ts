import type {
  ApiResponse,
  CreateCustomerAccessRequest,
  CustomerAccessListData,
  CustomerAccessMutationData,
  CustomerAccessStatus,
} from '../types/api'
import { api } from './api'

export async function getCustomerAccessList(
  search: string,
  status: CustomerAccessStatus | 'all',
): Promise<CustomerAccessListData> {
  const response = await api.get<ApiResponse<CustomerAccessListData>>('/v1/customers', {
    params: { search: search.trim(), status },
  })
  return response.data.data
}

export async function createCustomerAccess(
  payload: CreateCustomerAccessRequest,
): Promise<CustomerAccessMutationData> {
  return (await api.post<ApiResponse<CustomerAccessMutationData>>('/v1/customers', payload)).data.data
}

export async function enableCustomerAccess(customerId: string): Promise<CustomerAccessMutationData> {
  return (await api.post<ApiResponse<CustomerAccessMutationData>>(`/v1/customers/${customerId}/enable`)).data.data
}

export async function stopCustomerAccess(customerId: string): Promise<CustomerAccessMutationData> {
  return (await api.post<ApiResponse<CustomerAccessMutationData>>(`/v1/customers/${customerId}/stop`)).data.data
}

export async function resumeCustomerAccess(customerId: string): Promise<CustomerAccessMutationData> {
  return (await api.post<ApiResponse<CustomerAccessMutationData>>(`/v1/customers/${customerId}/resume`)).data.data
}

export async function updateCustomerAccessExpiration(
  customerId: string,
  accessExpiresAt: string,
): Promise<CustomerAccessMutationData> {
  return (await api.patch<ApiResponse<CustomerAccessMutationData>>(
    `/v1/customers/${customerId}/access-expiration`,
    { access_expires_at: accessExpiresAt },
  )).data.data
}

export async function copyCustomerAccessUrl(customerId: string): Promise<string> {
  const response = await api.post<ApiResponse<{ access_url: string }>>(
    `/v1/customers/${customerId}/access-link/copy`,
  )
  return response.data.data.access_url
}
