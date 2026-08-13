export const CUSTOMER_SESSION_INVALID_EVENT = 'logo-generated:customer-session-invalid'

export function notifyCustomerSessionInvalid(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(CUSTOMER_SESSION_INVALID_EVENT))
}
