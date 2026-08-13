import axios from 'axios'
import { ChevronDown, Copy, Plus, Search, X } from 'lucide-react'
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { AdminNavigation } from '../components/AdminNavigation'
import { GlobalToast } from '../components/GlobalToast'
import {
  copyCustomerAccessUrl,
  createCustomerAccess,
  enableCustomerAccess,
  getCustomerAccessList,
  resumeCustomerAccess,
  stopCustomerAccess,
  updateCustomerAccessExpiration,
} from '../services/customerAccessService'
import { useToastStore } from '../stores/useToastStore'
import type { CustomerAccessListItem, CustomerAccessStatus } from '../types/api'

const statusLabels: Record<CustomerAccessStatus, string> = {
  unstarted: '未启动',
  active: '已启用',
  stopped: '已关停',
  expired: '已到期',
}

type StatusFilter = CustomerAccessStatus | 'all'
type DialogState = { type: 'create' } | { type: 'edit' | 'stop'; customer: CustomerAccessListItem } | null
const statusRefreshIntervalMs = 15_000

function shanghaiInputValue(value: string | Date): string {
  const date = typeof value === 'string' ? new Date(value) : value
  return new Date(date.getTime() + 8 * 60 * 60 * 1000).toISOString().slice(0, 16)
}

function shanghaiInputToUtc(value: string): string {
  return new Date(`${value}:00+08:00`).toISOString()
}

function formatExpiration(value: string | null): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    hourCycle: 'h23',
  }).format(new Date(value)).replaceAll('/', '-')
}

function CustomerDialog({
  dialog,
  busy,
  onClose,
  onCreate,
  onEdit,
  onStop,
}: {
  dialog: Exclude<DialogState, null>
  busy: boolean
  onClose: () => void
  onCreate: (name: string, days: 1 | 3 | 7, activate: boolean) => Promise<void>
  onEdit: (customer: CustomerAccessListItem, expiresAt: string) => Promise<void>
  onStop: (customer: CustomerAccessListItem) => Promise<void>
}) {
  const [name, setName] = useState('')
  const [days, setDays] = useState<1 | 3 | 7>(3)
  const [activate, setActivate] = useState(false)
  const [expiresAt, setExpiresAt] = useState(
    dialog.type === 'edit' && dialog.customer.access_expires_at
      ? shanghaiInputValue(dialog.customer.access_expires_at)
      : '',
  )
  const [error, setError] = useState('')
  const firstField = useRef<HTMLInputElement>(null)
  const [minExpiration] = useState(() => shanghaiInputValue(new Date(Date.now() + 60_000)))

  useEffect(() => { firstField.current?.focus() }, [])
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [busy, onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (dialog.type === 'create') {
      if (!name.trim()) { setError('请输入客户名称'); return }
      await onCreate(name.trim(), days, activate)
      return
    }
    if (dialog.type === 'edit') {
      if (!expiresAt) { setError('请选择未来的到期时间'); return }
      const expirationUtc = shanghaiInputToUtc(expiresAt)
      if (new Date(expirationUtc).getTime() <= Date.now()) {
        setError('到期时间必须晚于当前时间')
        return
      }
      await onEdit(dialog.customer, expirationUtc)
      return
    }
    await onStop(dialog.customer)
  }

  const title = dialog.type === 'create' ? '新增客户' : dialog.type === 'edit' ? '编辑有效至' : '确认关停'
  return <div className="customer-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="customer-dialog" role="dialog" aria-modal="true" aria-labelledby="customer-dialog-title">
      <header><h2 id="customer-dialog-title">{title}</h2><button type="button" title="关闭" aria-label="关闭" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <form onSubmit={(event) => void submit(event)}>
        <div className="customer-dialog-body">
          {dialog.type === 'create' && <>
            <label className="customer-form-field"><span>客户名称</span><input ref={firstField} value={name} maxLength={200} disabled={busy} onChange={(event) => setName(event.target.value)} /></label>
            <fieldset className="customer-validity-field"><legend>有效期</legend><div>{([1, 3, 7] as const).map((value) => <button type="button" className={days === value ? 'active' : ''} aria-pressed={days === value} disabled={busy} onClick={() => setDays(value)} key={value}>{value} 天</button>)}</div></fieldset>
            <label className="customer-toggle-row"><span>立即启用</span><input type="checkbox" checked={activate} disabled={busy} onChange={(event) => setActivate(event.target.checked)} /><i aria-hidden="true" /></label>
          </>}
          {dialog.type === 'edit' && <label className="customer-form-field"><span>有效至</span><input ref={firstField} type="datetime-local" min={minExpiration} value={expiresAt} disabled={busy} onChange={(event) => setExpiresAt(event.target.value)} /></label>}
          {dialog.type === 'stop' && <div className="customer-stop-confirm" tabIndex={-1}><b>{dialog.customer.name}</b><p>关停后客户将立即无法访问，当前会话也会失效。原到期时间保持不变。</p></div>}
          <p className={`customer-dialog-error${error ? ' visible' : ''}`} role={error ? 'alert' : undefined}>{error}</p>
        </div>
        <footer><button type="button" className="customer-button secondary" disabled={busy} onClick={onClose}>取消</button><button type="submit" className={`customer-button${dialog.type === 'stop' ? ' danger' : ' primary'}`} disabled={busy}>{busy && <span className="admin-button-spinner" aria-hidden="true" />}{busy ? '处理中' : dialog.type === 'create' ? '新增' : dialog.type === 'edit' ? '保存' : '确认关停'}</button></footer>
      </form>
    </section>
  </div>
}

export function CustomerAccessPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [items, setItems] = useState<CustomerAccessListItem[]>([])
  const [search, setSearch] = useState('')
  const [deferredSearch, setDeferredSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [dialog, setDialog] = useState<DialogState>(null)
  const [dialogBusy, setDialogBusy] = useState(false)
  const [rowBusy, setRowBusy] = useState<string | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => setDeferredSearch(search.trim()), 260)
    return () => window.clearTimeout(timer)
  }, [search])

  const load = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true)
      setLoadError('')
    }
    try {
      setItems((await getCustomerAccessList(deferredSearch, statusFilter)).items)
      if (silent) setLoadError('')
    } catch {
      if (!silent) setLoadError('客户列表加载失败，请重试')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [deferredSearch, statusFilter])

  useEffect(() => { void Promise.resolve().then(() => load()) }, [load])
  useEffect(() => {
    const refresh = () => { void load(true) }
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }
    const timer = window.setInterval(refresh, statusRefreshIntervalMs)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
    }
  }, [load])

  const mutateRow = async (customer: CustomerAccessListItem, action: () => Promise<unknown>, success: string) => {
    setRowBusy(customer.id)
    try {
      await action()
      showToast(success)
      await load()
    } catch {
      showToast('操作失败，请刷新后重试')
    } finally {
      setRowBusy(null)
    }
  }

  const createCustomer = async (name: string, days: 1 | 3 | 7, activate: boolean) => {
    setDialogBusy(true)
    try {
      await createCustomerAccess({ name, validity_days: days, activate_immediately: activate })
      setDialog(null)
      showToast('客户已新增')
      await load()
    } catch (error) {
      showToast(axios.isAxiosError(error) && error.response?.status === 422 ? '请检查客户信息' : '新增客户失败')
    } finally {
      setDialogBusy(false)
    }
  }

  const editExpiration = async (customer: CustomerAccessListItem, expiresAt: string) => {
    setDialogBusy(true)
    try {
      await updateCustomerAccessExpiration(customer.id, expiresAt)
      setDialog(null)
      showToast('有效至已更新')
      await load()
    } catch {
      showToast('到期时间更新失败')
    } finally {
      setDialogBusy(false)
    }
  }

  const stopAccess = async (customer: CustomerAccessListItem) => {
    setDialogBusy(true)
    try {
      await stopCustomerAccess(customer.id)
      setDialog(null)
      showToast('客户访问已关停')
      await load()
    } catch {
      showToast('关停失败，请刷新后重试')
    } finally {
      setDialogBusy(false)
    }
  }

  const copyLink = async (customer: CustomerAccessListItem) => {
    setRowBusy(customer.id)
    try {
      const accessUrl = await copyCustomerAccessUrl(customer.id)
      await navigator.clipboard.writeText(accessUrl)
      showToast('访问链接已复制')
    } catch {
      showToast('复制失败，请重试')
    } finally {
      setRowBusy(null)
    }
  }

  return <div className="internal-shell">
    <AdminNavigation />
    <main className="customer-access-page">
      <header className="customer-access-head"><div><h1>客户访问</h1></div><button className="customer-add-button" type="button" onClick={() => setDialog({ type: 'create' })}><Plus size={17} aria-hidden="true" />新增客户</button></header>
      <section className="customer-filter-bar" aria-label="客户检索">
        <label className="customer-search-field"><Search size={17} aria-hidden="true" /><input aria-label="搜索客户名称" placeholder="搜索客户名称" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        <label className="customer-status-filter"><select aria-label="按状态筛选客户" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}><option value="all">全部状态</option><option value="unstarted">未启动</option><option value="active">已启用</option><option value="stopped">已关停</option><option value="expired">已到期</option></select><ChevronDown size={16} aria-hidden="true" /></label>
      </section>
      <section className="customer-access-list" aria-busy={loading}>
        <div className="customer-access-table-wrap">
          <table className="customer-access-table">
            <thead><tr><th>客户</th><th>访问链接</th><th>状态</th><th>有效至</th><th>操作</th></tr></thead>
            <tbody>{items.map((customer) => {
              const busy = rowBusy === customer.id
              return <tr key={customer.id}>
                <td data-label="客户"><b>{customer.name}</b></td>
                <td data-label="访问链接"><div className="customer-link-cell"><span title={customer.masked_access_url}>{customer.masked_access_url}</span><button type="button" title="复制访问链接" aria-label={`复制 ${customer.name} 的访问链接`} disabled={busy} onClick={() => void copyLink(customer)}><Copy size={15} aria-hidden="true" /></button></div></td>
                <td data-label="状态"><span className={`customer-access-status ${customer.status}`}>{statusLabels[customer.status]}</span></td>
                <td data-label="有效至"><time>{formatExpiration(customer.access_expires_at)}</time></td>
                <td data-label="操作"><div className="customer-row-actions">
                  {customer.status === 'unstarted' && <button type="button" disabled={busy} onClick={() => void mutateRow(customer, () => enableCustomerAccess(customer.id), '客户访问已启用')}>启用</button>}
                  {customer.status === 'active' && <><button type="button" disabled={busy} onClick={() => setDialog({ type: 'edit', customer })}>编辑</button><button type="button" className="danger" disabled={busy} onClick={() => setDialog({ type: 'stop', customer })}>关停</button></>}
                  {customer.status === 'stopped' && <><button type="button" disabled={busy} onClick={() => void mutateRow(customer, () => resumeCustomerAccess(customer.id), '客户访问已恢复')}>恢复</button><button type="button" disabled={busy} onClick={() => setDialog({ type: 'edit', customer })}>编辑</button></>}
                  {customer.status === 'expired' && <button type="button" disabled={busy} onClick={() => setDialog({ type: 'edit', customer })}>编辑</button>}
                </div></td>
              </tr>
            })}</tbody>
          </table>
          {!loading && !loadError && items.length === 0 && <div className="customer-access-empty">没有符合条件的客户</div>}
          {loading && <div className="customer-access-loading"><span className="admin-session-spinner" />正在加载...</div>}
          {!loading && loadError && <div className="customer-access-error"><span>{loadError}</span><button type="button" onClick={() => void load()}>重新加载</button></div>}
        </div>
      </section>
    </main>
    {dialog && <CustomerDialog dialog={dialog} busy={dialogBusy} onClose={() => setDialog(null)} onCreate={createCustomer} onEdit={editExpiration} onStop={stopAccess} />}
    <GlobalToast />
  </div>
}
