import { create } from 'zustand'
import { getCustomerSession } from '../services/authService'
import { CUSTOMER_SESSION_INVALID_EVENT } from '../utils/customerSession'
import { useGenerationStore } from './useGenerationStore'

type AccessStatus = 'unknown' | 'checking' | 'authorized' | 'unauthorized'
const useMock = import.meta.env.VITE_USE_MOCK === 'true'

interface AccessState {
  status: AccessStatus
  authorize: () => void
  clear: () => void
  invalidateSession: () => void
  checkSession: (options?: { silent?: boolean }) => Promise<void>
}

let sessionCheckPromise: Promise<boolean> | null = null

function requestCustomerSession(): Promise<boolean> {
  if (!sessionCheckPromise) {
    sessionCheckPromise = getCustomerSession().finally(() => {
      sessionCheckPromise = null
    })
  }
  return sessionCheckPromise
}

export const useAccessStore = create<AccessState>((set, get) => ({
  status: 'unknown',
  authorize: () => {
    if (useMock) window.localStorage.setItem('logo-generated.mock-access-authorized', 'true')
    set({ status: 'authorized' })
  },
  clear: () => {
    if (useMock) window.localStorage.removeItem('logo-generated.mock-access-authorized')
    set({ status: 'unauthorized' })
  },
  invalidateSession: () => {
    if (useMock) window.localStorage.removeItem('logo-generated.mock-access-authorized')
    useGenerationStore.getState().clearCustomerState()
    set({ status: 'unauthorized' })
  },
  checkSession: async ({ silent = false } = {}) => {
    if (get().status === 'checking' && sessionCheckPromise) {
      await sessionCheckPromise
      return
    }
    if (!silent) set({ status: 'checking' })
    try {
      set({ status: (await requestCustomerSession()) ? 'authorized' : 'unauthorized' })
    } catch {
      if (!silent) set({ status: 'unauthorized' })
    }
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener(CUSTOMER_SESSION_INVALID_EVENT, () => {
    useAccessStore.getState().invalidateSession()
  })
}
