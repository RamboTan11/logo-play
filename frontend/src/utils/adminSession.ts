export const ADMIN_SESSION_INVALID_EVENT = 'logo-generated:admin-session-invalid'

export function notifyAdminSessionInvalid(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(ADMIN_SESSION_INVALID_EVENT))
}
