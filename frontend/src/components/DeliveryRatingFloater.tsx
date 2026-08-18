import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, Sparkles, Star } from 'lucide-react'
import { getMyTasks, submitTaskRating } from '../services/designTasksService'
import type { MyTaskListItem } from '../types/api'
import { useClientLanguage } from '../i18n/useClientLanguage'

const ratingLabels = ['很糟糕', '需要改进', '还不错', '很满意', '太棒了']

export function DeliveryRatingFloater() {
  const { t } = useClientLanguage()
  const [tasks, setTasks] = useState<MyTaskListItem[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [hoveredRating, setHoveredRating] = useState<number | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    void getMyTasks().then((nextTasks) => {
      if (active) setTasks(nextTasks)
    }).catch(() => {
      // The rating control is optional; the surrounding client page remains usable if it cannot load.
    })
    return () => { active = false }
  }, [])

  const deliveredTask = useMemo(() => tasks
    .filter((task) => task.status === 'completed')
    .sort((left, right) => right.submitted_at.localeCompare(left.submitted_at))[0] ?? null, [tasks])

  if (!deliveredTask) return null

  const currentRating = hoveredRating ?? deliveredTask.rating ?? 0
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
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '评分提交失败，请稍后重试。')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <aside className={`delivery-rating-floater${isOpen ? ' is-open' : ''}`} aria-label={t('交付评分')}>
      {isOpen && <div className="delivery-rating-panel">
        <div className="delivery-rating-panel-heading">
          <div><span className="delivery-rating-kicker"><Sparkles size={13} aria-hidden="true" />{t('交付回响')}</span><strong>{t('这一版，感觉如何？')}</strong><small>{t('你的评价会帮助我们继续变好')}</small></div>
          <button className="delivery-rating-collapse" type="button" aria-label={t('收起评分')} onClick={() => { setIsOpen(false); setHoveredRating(null) }}><ChevronDown size={17} aria-hidden="true" /></button>
        </div>
        <div className="delivery-rating-choices" role="radiogroup" aria-label={t('选择交付评分')} onMouseLeave={() => setHoveredRating(null)}>
          {[1, 2, 3, 4, 5].map((rating) => <button key={rating} type="button" className={rating <= currentRating ? 'active' : ''} role="radio" aria-checked={deliveredTask.rating === rating} aria-label={`${rating} ${t('分')} - ${t(ratingLabels[rating - 1])}`} disabled={isSubmitting} onMouseEnter={() => setHoveredRating(rating)} onFocus={() => setHoveredRating(rating)} onBlur={() => setHoveredRating(null)} onClick={() => void submitRating(rating)}><Star size={24} fill="currentColor" strokeWidth={1.6} aria-hidden="true" /><span>{rating}</span></button>)}
        </div>
        <div className="delivery-rating-feedback" aria-live="polite">{isSubmitting ? t('正在收集这份心情...') : saved ? t('已收到，这份评价已记下。') : error ?? (deliveredTask.rating ? t('可以随时重新点亮另一颗星。') : t('点亮一颗星，告诉我们你的真实感受。'))}</div>
      </div>}
      {!isOpen && <button className="delivery-rating-launcher" type="button" onClick={() => { setIsOpen(true); setSaved(false); setError(null) }}><Star size={17} fill="currentColor" strokeWidth={1.6} aria-hidden="true" /><span>{t(deliveredTask.rating ? '重新评价' : '给这次交付打个分')}</span></button>}
    </aside>
  )
}
