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
  progressive?: boolean
}

/** Cache authenticated API images, defer off-screen requests, and optionally upgrade previews. */
export function CachedImage({
  src,
  loading = 'lazy',
  thumbnail = false,
  progressive = false,
  className,
  onLoad,
  onError,
  ...props
}: CachedImageProps) {
  const protectedApiImage = src.includes('/api/')
  const thumbnailSrc = protectedApiImage
    ? `${src}${src.includes('?') ? '&' : '?'}thumbnail=true`
    : src
  const requestedSrc = (thumbnail || progressive) && protectedApiImage ? thumbnailSrc : src
  const upgradeSrc = progressive && protectedApiImage ? src : null
  const imageRef = useRef<HTMLImageElement>(null)
  const [shouldLoad, setShouldLoad] = useState(loading === 'eager')
  const [loaded, setLoaded] = useState(false)
  const [resolvedSrc, setResolvedSrc] = useState<string | null>(() => (
    requestedSrc.includes('/api/') ? null : requestedSrc
  ))

  useEffect(() => {
    setResolvedSrc(requestedSrc.includes('/api/') ? null : requestedSrc)
    setShouldLoad(loading === 'eager')
    setLoaded(false)
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

  useEffect(() => {
    if (!shouldLoad || !upgradeSrc || !resolvedSrc) return
    let active = true
    void cachedImageUrl(upgradeSrc).then(
      (objectUrl) => { if (active) setResolvedSrc(objectUrl) },
      // Keep the already rendered preview when the optional upgrade fails.
      () => undefined,
    )
    return () => { active = false }
  }, [shouldLoad, upgradeSrc, resolvedSrc])

  return <img
    ref={imageRef}
    src={resolvedSrc ?? undefined}
    className={`cached-image${loaded ? ' is-loaded' : ''}${className ? ` ${className}` : ''}`}
    aria-busy={!loaded}
    onLoad={(event) => {
      setLoaded(true)
      onLoad?.(event)
    }}
    onError={(event) => {
      setLoaded(true)
      onError?.(event)
    }}
    {...props}
  />
}
