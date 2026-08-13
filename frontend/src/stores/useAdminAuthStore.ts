import { create } from 'zustand'
import { getAdminSession, logoutAdmin } from '../services/adminAuthService'

type AdminAuthStatus = 'unknown' | 'checking' | 'authorized' | 'unauthorized'

interface AdminAuthState {
  status: AdminAuthStatus
  authorize: () => void
  checkSession: () => Promise<void>
  logout: () => Promise<void>
}

export const useAdminAuthStore = create<AdminAuthState>((set, get) => ({
  status: 'unknown',
  authorize: () => set({ status: 'authorized' }),
  checkSession: async () => {
    if (get().status === 'checking') return
    set({ status: 'checking' })
    set({ status: (await getAdminSession()) ? 'authorized' : 'unauthorized' })
  },
  logout: async () => {
    try {
      await logoutAdmin()
    } finally {
      set({ status: 'unauthorized' })
    }
  },
}))
