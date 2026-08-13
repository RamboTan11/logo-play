import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ClientShell } from '../components/ClientShell'
import { getMyTask } from '../services/designTasksService'
import { useToastStore } from '../stores/useToastStore'
import type { MyTaskDetail } from '../types/api'
import { useClientLanguage } from '../i18n/useClientLanguage'

function displayEmpty(value: string | null): string {
  return value?.trim() || '-'
}

export function MyTaskDetailPage() {
  const { t } = useClientLanguage()
  const { taskId = '' } = useParams()
  const navigate = useNavigate()
  const showToast = useToastStore((state) => state.showToast)
  const [task, setTask] = useState<MyTaskDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let active = true
    getMyTask(taskId)
      .then((nextTask) => { if (active) setTask(nextTask) })
      .catch(() => { if (active) showToast(t('方案详情加载失败。')) })
      .finally(() => { if (active) setIsLoading(false) })
    return () => { active = false }
  }, [showToast, t, taskId])

  if (isLoading) return <ClientShell><main className="client-main task-detail-main"><p className="my-plans-loading">{t('正在加载任务...')}</p></main></ClientShell>
  if (!task) return <ClientShell><main className="client-main task-detail-main"><button className="secondary" type="button" onClick={() => navigate('/my-plans')}>{t('返回我的方案')}</button><p className="my-plans-empty">{t('未找到该任务')}</p></main></ClientShell>

  return (
    <ClientShell>
      <main className="client-main task-detail-main">
        <button className="task-back" type="button" onClick={() => navigate('/my-plans')}>← {t('返回我的方案')}</button>
        <header className="task-detail-head"><h1 className="display">{task.domain}</h1></header>
        <section className="customer-task-detail-layout">
          <article className="task-detail-adopted"><h2>{t('方案详情')}</h2><div className="task-detail-snapshots"><section><h3>{t('选择方案')}</h3><img src={task.adopted_image_url} alt={t('选择方案')} /></section><section><h3>{t('精修终稿')}</h3>{task.delivery_image_url ? <img src={task.delivery_image_url} alt={t('精修终稿')} /> : <div className="client-task-delivery-pending" role="img" aria-label={t('精修终稿待交付')}><span>{t('待交付')}</span></div>}</section></div></article>
          <aside className="task-detail-info"><h2>{t('人工精修建议')}</h2><div><b>{displayEmpty(task.adoption_suggestion)}</b></div></aside>
        </section>
      </main>
    </ClientShell>
  )
}
