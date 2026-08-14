import { create } from 'zustand'
import { getAdminSession, logoutAdmin } from '../services/adminAuthService'

type AdminAuthStatus = 'unknown' | 'checking' | 'authorized' | 'unauthorized'

interface AdminAuthState {
  status: AdminAuthStatus
  authorize: () => void
  invalidate: () => void
  checkSession: () => Promise<void>
  logout: () => Promise<void>
}

let sessionCheckPromise: Promise<boolean> | null = null

function requestAdminSession(): Promise<boolean> {
  if (!sessionCheckPromise) {
    sessionCheckPromise = getAdminSession().finally(() => {
      sessionCheckPromise = null
    })
  }
  return sessionCheckPromise
}

export const useAdminAuthStore = create<AdminAuthState>((set, get) => ({
  status: 'unknown',
  authorize: () => set({ status: 'authorized' }),
  invalidate: () => set({ status: 'unauthorized' }),
  checkSession: async () => {
    if (get().status === 'checking' && sessionCheckPromise) {
      await sessionCheckPromise
      return
    }
    set({ status: 'checking' })
    set({ status: (await requestAdminSession()) ? 'authorized' : 'unauthorized' })
  },
  logout: async () => {
    try {
      await logoutAdmin()
    } finally {
      set({ status: 'unauthorized' })
    }
  },
}))
