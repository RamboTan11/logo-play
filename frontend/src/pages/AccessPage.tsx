import { CircleAlert, LoaderCircle } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { verifyAccess, type AccessResult } from '../services/authService'
import { useAccessStore } from '../stores/useAccessStore'
import { useClientLanguage } from '../i18n/useClientLanguage'
import { LanguageSwitcher } from '../components/LanguageSwitcher'

const messages: Record<Exclude<AccessResult, 'valid'>, { title: string; detail: string }> = {
  invalid: { title: '访问链接无效', detail: '请确认你打开的是当前有效的访问链接。' },
  unstarted: { title: '访问尚未启用', detail: '当前访问权限尚未开始，请联系项目负责人。' },
  stopped: { title: '访问已关停', detail: '当前访问权限已关停，请联系项目负责人。' },
  expired: { title: '访问链接已到期', detail: '本次访问权限已结束，请联系项目负责人。' },
  unavailable: { title: '暂时无法验证', detail: '服务暂时不可用，请稍后重新打开访问链接。' },
}

export function AccessPage() {
  const { t } = useClientLanguage()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const authorize = useAccessStore((state) => state.authorize)
  const clear = useAccessStore((state) => state.clear)
  const token = params.get('token')?.trim() ?? ''
  const [result, setResult] = useState<Exclude<AccessResult, 'valid'> | null>(token ? null : 'invalid')
  const verificationRef = useRef<Promise<AccessResult> | null>(null)

  useEffect(() => {
    let active = true
    clear()
    if (!token) {
      return () => { active = false }
    }
    window.history.replaceState({}, '', '/access')
    verificationRef.current ??= verifyAccess(token)
    void verificationRef.current.then((accessResult) => {
      if (!active) return
      if (accessResult === 'valid') {
        authorize()
        navigate('/create', { replace: true })
        return
      }
      setResult(accessResult)
    })
    return () => { active = false }
  }, [authorize, clear, navigate, token])

  return (
    <div className="client-shell access-shell">
      <div className="access-language-control"><LanguageSwitcher /></div>
      <main className="access-main">
        <section className="access-card" aria-live="polite">
          {result ? <>
            <div className="access-state-heading">
              <CircleAlert className="access-state-icon" size={24} aria-hidden="true" />
              <h1>{t(messages[result].title)}</h1>
            </div>
            <p>{t(messages[result].detail)}</p>
          </> : <>
            <div className="access-state-heading">
              <LoaderCircle className="access-state-icon access-state-loading" size={24} aria-hidden="true" />
              <h1>{t('正在验证访问')}</h1>
            </div>
            <p>{t('正在确认你的访问权限，请稍候。')}</p>
          </>}
        </section>
      </main>
    </div>
  )
}
