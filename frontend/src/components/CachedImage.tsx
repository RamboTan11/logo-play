import { useEffect, useRef, useState } from 'react'
import type { ComponentPropsWithoutRef } from 'react'

const imageUrlCache = new Map<string, Promise<string>>()

function cachedImageUrl(source: string): Promise<string> {
  const existing = imageUrlCache.get(source)
  if (existing) return existing

  const pending = fetch(source, { credentials: 'include' })
    .then((response) => {
      if (!response.ok) throw new Error(`Image request failed with ${response.status}`)
      return response.blob()
    })
    .then((blob) => URL.createObjectURL(blob))
    .catch((error: unknown) => {
      imageUrlCache.delete(source)
      throw error
    })
  imageUrlCache.set(source, pending)
  return pending
}

type CachedImageProps = Omit<ComponentPropsWithoutRef<'img'>, 'src' | 'loading'> & {
  src: string
  loading?: 'eager' | 'lazy'
  thumbnail?: boolean
}

/** Cache authenticated API images for the current tab and defer off-screen requests. */
export function CachedImage({ src, loading = 'lazy', thumbnail = false, ...props }: CachedImageProps) {
  const requestedSrc = thumbnail && src.includes('/api/')
    ? `${src}${src.includes('?') ? '&' : '?'}thumbnail=true`
    : src
  const imageRef = useRef<HTMLImageElement>(null)
  const [shouldLoad, setShouldLoad] = useState(loading === 'eager')
  const [resolvedSrc, setResolvedSrc] = useState<string | null>(() => (
    requestedSrc.includes('/api/') ? null : requestedSrc
  ))

  useEffect(() => {
    setResolvedSrc(requestedSrc.includes('/api/') ? null : requestedSrc)
    setShouldLoad(loading === 'eager')
  }, [requestedSrc, loading])

  useEffect(() => {
    if (shouldLoad || loading !== 'lazy') return
    const element = imageRef.current
    if (!element || !('IntersectionObserver' in window)) {
      setShouldLoad(true)
      return
    }
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry?.isIntersecting) setShouldLoad(true) },
      { rootMargin: '320px' },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [loading, shouldLoad])

  useEffect(() => {
    if (!shouldLoad || !requestedSrc.includes('/api/')) return
    let active = true
    void cachedImageUrl(requestedSrc).then(
      (objectUrl) => { if (active) setResolvedSrc(objectUrl) },
      () => { if (active) setResolvedSrc(requestedSrc) },
    )
    return () => { active = false }
  }, [shouldLoad, requestedSrc])

  return <img ref={imageRef} src={resolvedSrc ?? undefined} {...props} />
}
