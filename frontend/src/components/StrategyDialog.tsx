import { X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { PropsWithChildren, ReactNode } from 'react'

interface StrategyDialogProps extends PropsWithChildren {
  title: string
  description?: string
  footer?: ReactNode
  wide?: boolean
  variant?: 'default' | 'confirmation'
  onClose: () => void
}

export function StrategyDialog({ title, description, footer, wide = false, variant = 'default', onClose, children }: StrategyDialogProps) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    closeRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [])

  return (
    <div className="strategy-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className={`strategy-dialog${wide ? ' wide' : ''}${variant === 'confirmation' ? ' confirmation' : ''}`} role="dialog" aria-modal="true" aria-labelledby="strategy-dialog-title">
        <header className="strategy-dialog-head">
          <div>
            <h2 id="strategy-dialog-title">{title}</h2>
            {description && <p>{description}</p>}
          </div>
          <button ref={closeRef} className="strategy-icon-button" type="button" title="关闭" aria-label="关闭弹窗" onClick={onClose}><X size={17} /></button>
        </header>
        {children && <div className="strategy-dialog-body">{children}</div>}
        {footer && <footer className="strategy-dialog-footer">{footer}</footer>}
      </section>
    </div>
  )
}
