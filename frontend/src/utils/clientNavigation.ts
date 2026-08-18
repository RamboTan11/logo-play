const lastCreationPathKey = 'logo-generated.last-creation-path'

export function rememberLastCreationPath(path: string): void {
  if (typeof window === 'undefined') return
  if (path === '/create' || path === '/results') {
    window.sessionStorage.setItem(lastCreationPathKey, path)
  }
}

export function getLastCreationPath(): string {
  if (typeof window === 'undefined') return '/create'
  const path = window.sessionStorage.getItem(lastCreationPathKey)
  return path === '/results' || path === '/create' ? path : '/create'
}
