import { create } from 'zustand'

let toastTimer: number | null = null

export interface ToastAction {
  label: string
  to: string
  suffix?: string
}

interface ToastState {
  message: string | null
  action: ToastAction | null
  showToast: (message: string, action?: ToastAction) => void
  clearToast: () => void
}

export const useToastStore = create<ToastState>((set) => ({
  message: null,
  action: null,
  showToast: (message, action: ToastAction | null = null) => {
    if (toastTimer !== null) window.clearTimeout(toastTimer)
    set({ message, action })
    toastTimer = window.setTimeout(() => {
      set({ message: null, action: null })
      toastTimer = null
    }, 3200)
  },
  clearToast: () => {
    if (toastTimer !== null) window.clearTimeout(toastTimer)
    toastTimer = null
    set({ message: null, action: null })
  },
}))
