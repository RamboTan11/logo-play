import { useEffect, useMemo, useRef, useState } from 'react'
import { Star } from 'lucide-react'
import { getMyTasks, submitTaskRating } from '../services/designTasksService'
import type { MyTaskListItem } from '../types/api'
import { useClientLanguage } from '../i18n/useClientLanguage'

export function DeliveryRatingFloater() {
  const { t } = useClientLanguage()
  const [tasks, setTasks] = useState<MyTaskListItem[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [hoveredRating, setHoveredRating] = useState<number | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const collapseTimerRef = useRef<number | null>(null)
  const floaterRef = useRef<HTMLElement>(null)

  useEffect(() => {
    let active = true
    void getMyTasks().then((nextTasks) => {
      if (active) setTasks(nextTasks)
    }).catch(() => {
      // The rating control is optional; the surrounding client page remains usable if it cannot load.
    })
    return () => { active = false }
  }, [])

  useEffect(() => () => {
    if (collapseTimerRef.current != null) window.clearTimeout(collapseTimerRef.current)
  }, [])

  useEffect(() => {
    if (!isOpen) return
    const closeOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target
      if (target instanceof Node && !floaterRef.current?.contains(target)) closePanel()
    }
    document.addEventListener('pointerdown', closeOnOutsidePointer)
    return () => document.removeEventListener('pointerdown', closeOnOutsidePointer)
  }, [isOpen])

  const deliveredTask = useMemo(() => tasks
    .filter((task) => task.status === 'completed')
    .sort((left, right) => right.submitted_at.localeCompare(left.submitted_at))[0] ?? null, [tasks])

  if (!deliveredTask) return null

  const hasRated = Boolean(deliveredTask.rating)
  const currentRating = hoveredRating ?? deliveredTask.rating ?? 0
  const clearCollapseTimer = () => {
    if (collapseTimerRef.current != null) {
      window.clearTimeout(collapseTimerRef.current)
      collapseTimerRef.current = null
    }
  }
  const closePanel = () => {
    clearCollapseTimer()
    setIsOpen(false)
    setHoveredRating(null)
    setSaved(false)
  }
  const submitRating = async (rating: number) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await submitTaskRating(deliveredTask.id, rating)
      setTasks((current) => current.map((task) => task.id === updated.id ? updated : task))
      setHoveredRating(null)
      setSaved(true)
      clearCollapseTimer()
      collapseTimerRef.current = window.setTimeout(closePanel, 1200)
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '评分提交失败，请稍后重试。')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <aside ref={floaterRef} className={`delivery-rating-floater${isOpen ? ' is-open' : ''}${saved ? ' is-saved' : ''}`} aria-label={t('交付评分')}>
      <button className={`delivery-rating-launcher${hasRated ? ' is-rated' : ''}`} type="button" onClick={() => { clearCollapseTimer(); setIsOpen(true); setError(null) }} aria-expanded={isOpen} aria-label={t('交付评分')}>
        <Star size={22} fill="currentColor" strokeWidth={1.7} aria-hidden="true" />
      </button>
      <div className="delivery-rating-panel" aria-hidden={!isOpen}>
        {saved ? <div className="delivery-rating-thanks" aria-live="polite"><span className="delivery-rating-thanks-star"><Star size={22} fill="currentColor" strokeWidth={1.7} aria-hidden="true" /></span><strong>{t('感谢您的评价')}</strong></div> : <>
          <span className="delivery-rating-title">{t('本次服务是否满意')}</span>
          <div className="delivery-rating-choices" role="radiogroup" aria-label={t('选择交付评分')} onMouseLeave={() => setHoveredRating(null)}>
            {[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" className={rating <= currentRating ? 'active' : ''} role="radio" aria-checked={deliveredTask.rating === rating} aria-label={`${rating} ${t('分')}`} disabled={isSubmitting} onMouseEnter={() => setHoveredRating(rating)} onFocus={() => setHoveredRating(rating)} onBlur={() => setHoveredRating(null)} onClick={() => void submitRating(rating)}><Star size={25} fill="currentColor" strokeWidth={1.6} aria-hidden="true" /></button>)}
          </div>
          {error && <div className="delivery-rating-feedback" role="alert">{error}</div>}
        </>}
      </div>
    </aside>
  )
}
