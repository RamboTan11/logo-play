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

let sessionCheckPending = false

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
    if (sessionCheckPending || get().status === 'checking') return
    sessionCheckPending = true
    if (!silent) set({ status: 'checking' })
    try {
      set({ status: (await getCustomerSession()) ? 'authorized' : 'unauthorized' })
    } catch {
      if (!silent) set({ status: 'unauthorized' })
    } finally {
      sessionCheckPending = false
    }
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener(CUSTOMER_SESSION_INVALID_EVENT, () => {
    useAccessStore.getState().invalidateSession()
  })
}
