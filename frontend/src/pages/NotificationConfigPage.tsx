import axios from 'axios'
import {
  BellRing,
  ChevronDown,
  ChevronUp,
  Clock3,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Send,
  Trash2,
  X,
} from 'lucide-react'
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdminNavigation } from '../components/AdminNavigation'
import { GlobalToast } from '../components/GlobalToast'
import {
  createLarkRecipient,
  deleteLarkRecipient,
  getLarkChannel,
  getLarkRecipients,
  getLarkRules,
  getRecentLarkDeliveries,
  sendLarkTest,
  updateLarkChannel,
  updateLarkRecipient,
  updateLarkRules,
} from '../services/larkNotificationService'
import { useToastStore } from '../stores/useToastStore'
import { formatBeijingDateTime } from '../utils/dateTime'
import type {
  LarkChannelDto,
  LarkDeliveryFilter,
  LarkDeliveryStatus,
  LarkEventType,
  LarkNotificationRuleDto,
  LarkRecentDeliveryDto,
  LarkRecipientDto,
} from '../types/larkNotification'

interface RuleDefinition {
  eventType: LarkEventType
  title: string
  subtitle: (threshold: string) => string
  description: string
  overdue: boolean
  groupOnly: boolean
}

interface RuleDraft {
  enabled: boolean
  mentionAll: boolean
  recipientIds: string[]
  thresholdHours: string
  repeatIntervalHours: string
  maxRepeatCount: string
}

interface ChannelDraft {
  enabled: boolean
  groupLabel: string
  webhook: string
  signingEnabled: boolean
  signingSecret: string
}

const ruleDefinitions: RuleDefinition[] = [
  { eventType: 'task.adoption_submitted', title: '新任务提醒', subtitle: () => '客户已提交采用方案，等待接单', description: '用户提交采用后立即通知', overdue: false, groupOnly: false },
  { eventType: 'task.waiting_assignment_overdue', title: '待接单提醒', subtitle: (hours) => `任务提交已超过 ${hours || '-'} 小时，仍未接单`, description: '进入待接单后超过阈值仍无人接单', overdue: true, groupOnly: false },
  { eventType: 'task.upload_overdue', title: '上传图片提醒', subtitle: (hours) => `任务接单已超过 ${hours || '-'} 小时，尚未上传交付图片`, description: '进入处理中后超过阈值仍未上传图片', overdue: true, groupOnly: false },
  { eventType: 'task.adoption_changed_before_acceptance', title: '方案变更通知', subtitle: () => '客户已修改采用方案', description: '后台接单前，客户修改采用方案', overdue: false, groupOnly: false },
  { eventType: 'task.adoption_changed_in_progress', title: '方案变更通知', subtitle: () => '客户已修改采用方案', description: '后台接单后、上传图片前，客户修改采用方案', overdue: false, groupOnly: false },
  { eventType: 'task.delivery_uploaded', title: '图片上传成功', subtitle: () => '交付图片已上传，任务已完成', description: '后台上传交付图片后仅通知群聊', overdue: false, groupOnly: true },
]

const defaultRules = ruleDefinitions.reduce<Record<LarkEventType, RuleDraft>>((result, definition) => {
  result[definition.eventType] = {
    enabled: true,
    mentionAll: false,
    recipientIds: [],
    thresholdHours: definition.eventType === 'task.upload_overdue' ? '36' : definition.overdue ? '6' : '',
    repeatIntervalHours: definition.overdue ? '12' : '',
    maxRepeatCount: definition.overdue ? '3' : '',
  }
  return result
}, {} as Record<LarkEventType, RuleDraft>)

const statusLabels: Record<LarkDeliveryStatus, string> = {
  accepted: '已发送',
  retrying: '重试中',
  failed: '发送失败',
}

function formatTime(value: string | null): string {
  return value ? formatBeijingDateTime(value) : '-'
}

function requestError(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const message = (error.response?.data as { message?: unknown } | undefined)?.message
    if (typeof message === 'string' && message.trim()) return message
  }
  return error instanceof Error && error.message ? error.message : fallback
}

function positiveInteger(value: string, maximum = Number.MAX_SAFE_INTEGER): number | null {
  if (!/^\d+$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 && parsed <= maximum ? parsed : null
}

function channelDraft(channel: LarkChannelDto): ChannelDraft {
  return {
    enabled: channel.enabled,
    groupLabel: channel.group_label ?? '',
    webhook: '',
    signingEnabled: channel.signing_enabled,
    signingSecret: '',
  }
}

function rulesDraft(rules: LarkNotificationRuleDto[]): Record<LarkEventType, RuleDraft> {
  const next = structuredClone(defaultRules)
  rules.forEach((rule) => {
    next[rule.event_type] = {
      enabled: rule.enabled,
      mentionAll: rule.mention_all,
      recipientIds: rule.recipient_ids,
      thresholdHours: rule.threshold_hours === null ? '' : String(rule.threshold_hours),
      repeatIntervalHours: rule.repeat_interval_hours === null ? '' : String(rule.repeat_interval_hours),
      maxRepeatCount: rule.max_repeat_count === null ? '' : String(rule.max_repeat_count),
    }
  })
  return next
}

function isValidLarkWebhook(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'https:'
      && url.hostname === 'open.larksuite.com'
      && url.pathname.startsWith('/open-apis/bot/v2/hook/')
      && !url.username
      && !url.password
      && !url.search
      && !url.hash
  } catch {
    return false
  }
}

function RecipientDialog({ recipient, busy, onClose, onSave }: {
  recipient: LarkRecipientDto | null
  busy: boolean
  onClose: () => void
  onSave: (payload: { displayName: string; openId: string; enabled: boolean }) => Promise<void>
}) {
  const [displayName, setDisplayName] = useState(recipient?.display_name ?? '')
  const [openId, setOpenId] = useState('')
  const [enabled, setEnabled] = useState(recipient?.enabled ?? true)
  const [error, setError] = useState('')
  const firstField = useRef<HTMLInputElement>(null)

  useEffect(() => { firstField.current?.focus() }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const normalizedOpenId = openId.trim()
    setError('')
    if (!recipient && !normalizedOpenId) { setError('请输入 Lark open_id'); return }
    if (normalizedOpenId && !/^ou_[A-Za-z0-9_-]{3,}$/.test(normalizedOpenId)) {
      setError('open_id 格式不正确，应以 ou_ 开头')
      return
    }
    if (displayName.trim().length > 100) { setError('人员名称不能超过 100 个字符'); return }
    await onSave({ displayName: displayName.trim(), openId: normalizedOpenId, enabled })
  }

  return <div className="lark-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="lark-modal" role="dialog" aria-modal="true" aria-labelledby="recipient-dialog-title">
      <header><div><h2 id="recipient-dialog-title">{recipient ? '编辑通知人员' : '新增通知人员'}</h2>{recipient && <p>当前 open_id：{recipient.open_id_masked}</p>}</div><button type="button" title="关闭" aria-label="关闭" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <form onSubmit={(event) => void submit(event)} noValidate>
        <div className="lark-modal-body">
          <label className="lark-field"><span>人员名称（选填）</span><input ref={firstField} maxLength={100} value={displayName} disabled={busy} onChange={(event) => setDisplayName(event.target.value)} placeholder="Lark 中便于识别的名称" /></label>
          <label className="lark-field"><span>{recipient ? '替换 open_id（选填）' : 'open_id'} {!recipient && <b>*</b>}</span><input type="password" autoComplete="new-password" value={openId} disabled={busy} onChange={(event) => setOpenId(event.target.value)} placeholder={recipient ? '留空保留当前值' : 'ou_...'} /></label>
          <label className="lark-switch-row"><span><b>启用人员</b><small>停用后不能被新规则选中</small></span><input type="checkbox" checked={enabled} disabled={busy} onChange={(event) => setEnabled(event.target.checked)} /><i aria-hidden="true" /></label>
          <p className={`lark-field-error${error ? ' visible' : ''}`} role={error ? 'alert' : undefined}>{error}</p>
        </div>
        <footer><button className="internal-button" type="button" disabled={busy} onClick={onClose}>取消</button><button className="internal-button primary" type="submit" disabled={busy}>{busy ? '保存中...' : '保存人员'}</button></footer>
      </form>
    </section>
  </div>
}

function TestDialog({ recipients, busy, onClose, onConfirm }: {
  recipients: LarkRecipientDto[]
  busy: boolean
  onClose: () => void
  onConfirm: (mentionEnabled: boolean, recipientIds: string[]) => Promise<void>
}) {
  const enabledRecipients = recipients.filter((recipient) => recipient.enabled)
  const [mentionEnabled, setMentionEnabled] = useState(false)
  const [recipientIds, setRecipientIds] = useState<string[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const confirm = async () => {
    setError('')
    if (mentionEnabled && !recipientIds.length) { setError('请选择至少一名启用人员'); return }
    await onConfirm(mentionEnabled, recipientIds)
  }

  return <div className="lark-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
    <section className="lark-modal compact" role="dialog" aria-modal="true" aria-labelledby="lark-test-title">
      <header><div><h2 id="lark-test-title">发送测试通知</h2><p>本次操作会向已保存的 Lark 群发送一张测试卡片。</p></div><button type="button" title="关闭" aria-label="关闭" disabled={busy} onClick={onClose}><X size={18} /></button></header>
      <div className="lark-modal-body">
        <label className="lark-switch-row"><span><b>同时 @ 指定人员</b><small>默认仅发送群通知</small></span><input type="checkbox" checked={mentionEnabled} disabled={busy || !enabledRecipients.length} onChange={(event) => { setMentionEnabled(event.target.checked); setRecipientIds([]); setError('') }} /><i aria-hidden="true" /></label>
        {mentionEnabled && <div className="lark-check-list" role="group" aria-label="测试通知人员">{enabledRecipients.map((recipient) => <label key={recipient.id}><input type="checkbox" checked={recipientIds.includes(recipient.id)} disabled={busy} onChange={(event) => setRecipientIds((current) => event.target.checked ? [...current, recipient.id] : current.filter((id) => id !== recipient.id))} /><span><b>{recipient.display_name || '未命名人员'}</b><small>{recipient.open_id_masked}</small></span></label>)}</div>}
        <p className={`lark-field-error${error ? ' visible' : ''}`} role={error ? 'alert' : undefined}>{error}</p>
      </div>
      <footer><button className="internal-button" type="button" disabled={busy} onClick={onClose}>取消</button><button className="internal-button primary" type="button" disabled={busy} onClick={() => void confirm()}>{busy ? '发送中...' : '确认发送'}</button></footer>
    </section>
  </div>
}

export function NotificationConfigPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [channel, setChannel] = useState<LarkChannelDto | null>(null)
  const [channelForm, setChannelForm] = useState<ChannelDraft | null>(null)
  const [recipients, setRecipients] = useState<LarkRecipientDto[]>([])
  const [rules, setRules] = useState<Record<LarkEventType, RuleDraft>>(structuredClone(defaultRules))
  const [selectedEvent, setSelectedEvent] = useState<LarkEventType>('task.adoption_submitted')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [channelError, setChannelError] = useState('')
  const [channelBusy, setChannelBusy] = useState(false)
  const [recipientDialog, setRecipientDialog] = useState<LarkRecipientDto | 'new' | null>(null)
  const [recipientBusy, setRecipientBusy] = useState(false)
  const [deletingRecipientId, setDeletingRecipientId] = useState<string | null>(null)
  const [rulesBusy, setRulesBusy] = useState(false)
  const [testOpen, setTestOpen] = useState(false)
  const [testBusy, setTestBusy] = useState(false)
  const [recentOpen, setRecentOpen] = useState(false)
  const [recentFilter, setRecentFilter] = useState<LarkDeliveryFilter>('all')
  const [recentItems, setRecentItems] = useState<LarkRecentDeliveryDto[]>([])
  const [recentLoading, setRecentLoading] = useState(false)
  const [recentError, setRecentError] = useState('')

  const loadConfiguration = useCallback(async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [nextChannel, nextRecipients, nextRules] = await Promise.all([getLarkChannel(), getLarkRecipients(), getLarkRules()])
      setChannel(nextChannel)
      setChannelForm(channelDraft(nextChannel))
      setRecipients(nextRecipients)
      setRules(rulesDraft(nextRules))
    } catch (error) {
      setLoadError(requestError(error, '通知配置加载失败，请重试'))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadRecent = useCallback(async () => {
    setRecentLoading(true)
    setRecentError('')
    try { setRecentItems(await getRecentLarkDeliveries(recentFilter)) }
    catch (error) { setRecentError(requestError(error, '最近发送状态加载失败')) }
    finally { setRecentLoading(false) }
  }, [recentFilter])

  useEffect(() => { void Promise.resolve().then(loadConfiguration) }, [loadConfiguration])
  useEffect(() => { if (recentOpen) void Promise.resolve().then(loadRecent) }, [loadRecent, recentOpen])

  const saveChannel = async (event: FormEvent) => {
    event.preventDefault()
    if (!channel || !channelForm || channelBusy) return
    const webhook = channelForm.webhook.trim()
    const signingSecret = channelForm.signingSecret.trim()
    setChannelError('')
    if (channelForm.groupLabel.trim().length > 120) { setChannelError('群名称备注不能超过 120 个字符'); return }
    if (channel.webhook_status === 'missing' && !webhook) { setChannelError('首次保存必须填写 Lark Webhook'); return }
    if (webhook && !isValidLarkWebhook(webhook)) { setChannelError('请输入国际版 Lark 群自定义机器人的有效 Webhook'); return }
    if (channelForm.signingEnabled && channel.signing_secret_status === 'missing' && !signingSecret) { setChannelError('启用签名校验时必须填写签名密钥'); return }
    setChannelBusy(true)
    try {
      const updated = await updateLarkChannel({
        enabled: channelForm.enabled,
        group_label: channelForm.groupLabel.trim() || null,
        signing_enabled: channelForm.signingEnabled,
        ...(webhook ? { webhook } : {}),
        ...(signingSecret ? { signing_secret: signingSecret } : {}),
      })
      setChannel(updated)
      setChannelForm(channelDraft(updated))
      showToast('Lark 通道配置已保存')
    } catch (error) {
      setChannelError(requestError(error, 'Lark 通道保存失败'))
    } finally { setChannelBusy(false) }
  }

  const saveRecipient = async ({ displayName, openId, enabled }: { displayName: string; openId: string; enabled: boolean }) => {
    setRecipientBusy(true)
    try {
      if (recipientDialog === 'new') {
        await createLarkRecipient({ display_name: displayName || null, open_id: openId, enabled })
        showToast('通知人员已新增')
      } else if (recipientDialog) {
        await updateLarkRecipient(recipientDialog.id, {
          display_name: displayName || null,
          enabled,
          ...(openId ? { open_id: openId } : {}),
        })
        showToast('通知人员已更新')
      }
      setRecipientDialog(null)
      setRecipients(await getLarkRecipients())
    } catch (error) {
      showToast(requestError(error, '通知人员保存失败'))
    } finally { setRecipientBusy(false) }
  }

  const removeRecipient = async (recipient: LarkRecipientDto) => {
    if (deletingRecipientId || !window.confirm(`删除通知人员“${recipient.display_name || recipient.open_id_masked}”？`)) return
    setDeletingRecipientId(recipient.id)
    try {
      await deleteLarkRecipient(recipient.id)
      setRecipients(await getLarkRecipients())
      showToast('通知人员已删除')
    } catch (error) { showToast(requestError(error, '该人员无法删除，可改为停用')) }
    finally { setDeletingRecipientId(null) }
  }

  const updateRuleDraft = (eventType: LarkEventType, patch: Partial<RuleDraft>) => {
    setRules((current) => ({ ...current, [eventType]: { ...current[eventType], ...patch } }))
  }

  const enabledRecipientIds = useMemo(() => new Set(recipients.filter((recipient) => recipient.enabled).map((recipient) => recipient.id)), [recipients])
  const ruleError = (definition: RuleDefinition): string => {
    const draft = rules[definition.eventType]
    if (!draft.enabled) return ''
    if (!definition.groupOnly && !draft.mentionAll && !draft.recipientIds.some((id) => enabledRecipientIds.has(id))) return '启用该规则前，至少选择一种通知目标'
    if (definition.overdue && (positiveInteger(draft.thresholdHours, 720) === null || positiveInteger(draft.repeatIntervalHours, 720) === null)) return '首次阈值和重复间隔必须是 1 至 720 的整数'
    if (definition.overdue && positiveInteger(draft.maxRepeatCount, 100) === null) return '最大重复次数必须是 1 至 100 的整数'
    return ''
  }

  const saveRules = async () => {
    if (rulesBusy) return
    const invalidDefinition = ruleDefinitions.find((definition) => Boolean(ruleError(definition)))
    if (invalidDefinition) {
      setSelectedEvent(invalidDefinition.eventType)
      showToast(`${invalidDefinition.title}：${ruleError(invalidDefinition)}`)
      return
    }
    setRulesBusy(true)
    try {
      const updated = await updateLarkRules(ruleDefinitions.map((definition) => {
        const draft = rules[definition.eventType]
        return {
          event_type: definition.eventType,
          enabled: draft.enabled,
          mention_all: definition.groupOnly ? false : draft.mentionAll,
          recipient_ids: definition.groupOnly ? [] : draft.recipientIds,
          ...(definition.overdue ? {
            threshold_hours: positiveInteger(draft.thresholdHours, 720)!,
            repeat_interval_hours: positiveInteger(draft.repeatIntervalHours, 720)!,
            max_repeat_count: positiveInteger(draft.maxRepeatCount, 100)!,
          } : {}),
        }
      }))
      setRules(rulesDraft(updated))
      showToast('通知规则已保存')
    } catch (error) { showToast(requestError(error, '通知规则保存失败，草稿已保留')) }
    finally { setRulesBusy(false) }
  }

  const testNotification = async (mentionEnabled: boolean, recipientIds: string[]) => {
    if (testBusy) return
    setTestBusy(true)
    try {
      const result = await sendLarkTest({ mention_enabled: mentionEnabled, ...(mentionEnabled ? { recipient_ids: recipientIds } : {}) })
      setTestOpen(false)
      showToast(result.status === 'accepted' ? '测试通知已发送' : result.status === 'retrying' ? '测试通知正在重试' : '测试通知发送失败')
      const updatedChannel = await getLarkChannel()
      setChannel(updatedChannel)
      setChannelForm(channelDraft(updatedChannel))
      if (recentOpen) await loadRecent()
    } catch (error) { showToast(requestError(error, '测试通知发送失败')) }
    finally { setTestBusy(false) }
  }

  const selectedDefinition = ruleDefinitions.find((definition) => definition.eventType === selectedEvent)!
  const selectedRule = rules[selectedEvent]
  const previewRecipients = selectedDefinition.groupOnly || selectedRule.mentionAll
    ? []
    : recipients.filter((recipient) => selectedRule.recipientIds.includes(recipient.id))

  return <div className="internal-shell">
    <AdminNavigation />
    <main className="notification-config-page">
      <GlobalToast />
      <header className="notification-page-head"><div><h1>通知配置</h1><p>管理固定 Lark 群通道、通知人员和任务提醒规则。</p></div></header>
      {loading ? <div className="notification-load-state"><span className="admin-session-spinner" />正在加载通知配置...</div> : loadError ? <div className="notification-load-state error"><span>{loadError}</span><button className="internal-button" type="button" onClick={() => void loadConfiguration()}><RefreshCw size={15} />重试</button></div> : channel && channelForm && <>
        <section className="notification-section" aria-labelledby="lark-channel-title">
          <header className="notification-section-head"><div><h2 id="lark-channel-title">Lark 通道</h2><p>Secret 保存后不回显，留空表示保留当前配置。</p></div><span className={`notification-status ${channel.enabled ? 'accepted' : 'neutral'}`}>{channel.enabled ? '已启用' : '已停用'}</span></header>
          <form className="lark-channel-form" onSubmit={(event) => void saveChannel(event)} noValidate>
            <div className="lark-channel-status-grid">
              <div><span>Webhook</span><b>{channel.webhook_status === 'configured' ? '已配置' : '未配置'}</b></div>
              <div><span>签名密钥</span><b>{channel.signing_secret_status === 'configured' ? '已配置' : '未配置'}</b></div>
              <div><span>最近测试</span><b>{channel.last_test_status ? statusLabels[channel.last_test_status] : '-'}</b><small>{formatTime(channel.last_tested_at)}</small></div>
              <div><span>最近成功投递</span><b>{formatTime(channel.last_success_at)}</b></div>
            </div>
            <div className="lark-channel-fields">
              <label className="lark-field"><span>群名称备注</span><input maxLength={120} disabled={channelBusy} value={channelForm.groupLabel} onChange={(event) => setChannelForm({ ...channelForm, groupLabel: event.target.value })} placeholder="例如：设计任务协作群" /></label>
              <label className="lark-field"><span>{channel.webhook_status === 'configured' ? '替换 Webhook（选填）' : 'Webhook'} {channel.webhook_status === 'missing' && <b>*</b>}</span><input type="password" autoComplete="new-password" disabled={channelBusy} value={channelForm.webhook} onChange={(event) => setChannelForm({ ...channelForm, webhook: event.target.value })} placeholder={channel.webhook_status === 'configured' ? '留空保留当前地址' : 'https://open.larksuite.com/open-apis/bot/v2/hook/...'} /></label>
              <label className="lark-switch-row"><span><b>启用 Lark 通知</b><small>停用后保留通道与规则，但不再投递</small></span><input type="checkbox" checked={channelForm.enabled} disabled={channelBusy} onChange={(event) => setChannelForm({ ...channelForm, enabled: event.target.checked })} /><i aria-hidden="true" /></label>
              <label className="lark-switch-row"><span><b>启用签名校验</b><small>建议与群机器人安全设置保持一致</small></span><input type="checkbox" checked={channelForm.signingEnabled} disabled={channelBusy} onChange={(event) => setChannelForm({ ...channelForm, signingEnabled: event.target.checked })} /><i aria-hidden="true" /></label>
              {channelForm.signingEnabled && <label className="lark-field lark-channel-secret"><span>{channel.signing_secret_status === 'configured' ? '替换签名密钥（选填）' : '签名密钥'} {channel.signing_secret_status === 'missing' && <b>*</b>}</span><input type="password" autoComplete="new-password" disabled={channelBusy} value={channelForm.signingSecret} onChange={(event) => setChannelForm({ ...channelForm, signingSecret: event.target.value })} placeholder={channel.signing_secret_status === 'configured' ? '留空保留当前密钥' : '仅写入，不回显'} /></label>}
            </div>
            <p className={`lark-field-error${channelError ? ' visible' : ''}`} role={channelError ? 'alert' : undefined}>{channelError}</p>
            <div className="notification-section-actions"><button className="internal-button" type="button" disabled={channelBusy || channel.webhook_status !== 'configured' || !channel.enabled} onClick={() => setTestOpen(true)}><Send size={15} />发送测试通知</button><button className="internal-button primary" type="submit" disabled={channelBusy}>{channelBusy ? '保存中...' : '保存通道'}</button></div>
          </form>
        </section>

        <section className="notification-section" aria-labelledby="lark-recipients-title">
          <header className="notification-section-head"><div><h2 id="lark-recipients-title">通知人员</h2><p>人员名称用于后台识别，实际 @ 以 open_id 为准。</p></div><button className="internal-button primary" type="button" onClick={() => setRecipientDialog('new')}><Plus size={15} />新增人员</button></header>
          <div className="lark-recipient-table-wrap"><table className="lark-recipient-table"><thead><tr><th>人员名称</th><th>open_id</th><th>状态</th><th>更新时间</th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{recipients.map((recipient) => <tr key={recipient.id}><td data-label="人员名称"><b>{recipient.display_name || '未命名人员'}</b></td><td data-label="open_id"><code>{recipient.open_id_masked}</code></td><td data-label="状态"><span className={`notification-status ${recipient.enabled ? 'accepted' : 'neutral'}`}>{recipient.enabled ? '已启用' : '已停用'}</span></td><td data-label="更新时间">{formatTime(recipient.updated_at)}</td><td data-label="操作"><div className="lark-row-actions"><button type="button" title="编辑人员" aria-label={`编辑 ${recipient.display_name || recipient.open_id_masked}`} onClick={() => setRecipientDialog(recipient)}><Pencil size={15} /></button><button className="danger" type="button" title="删除人员" aria-label={`删除 ${recipient.display_name || recipient.open_id_masked}`} disabled={deletingRecipientId !== null} onClick={() => void removeRecipient(recipient)}><Trash2 size={15} /></button></div></td></tr>)}</tbody></table>{!recipients.length && <p className="notification-empty">暂无通知人员</p>}</div>
        </section>

        <section className="notification-section" aria-labelledby="lark-rules-title">
          <header className="notification-section-head"><div><h2 id="lark-rules-title">通知规则</h2><p>规则修改只作用于之后进入待接单或处理中的任务。</p></div><button className="internal-button primary" type="button" disabled={rulesBusy} onClick={() => void saveRules()}><Save size={15} />{rulesBusy ? '保存中...' : '保存通知规则'}</button></header>
          <div className="lark-rule-list">{ruleDefinitions.map((definition) => {
            const draft = rules[definition.eventType]
            const validation = ruleError(definition)
            return <article className="lark-rule-row" key={definition.eventType}>
              <header><div><h3>{definition.title}</h3><p>{definition.description}</p></div><label className="lark-switch-row compact"><span className="sr-only">启用 {definition.title}</span><input type="checkbox" checked={draft.enabled} disabled={rulesBusy} onChange={(event) => updateRuleDraft(definition.eventType, { enabled: event.target.checked })} /><i aria-hidden="true" /></label></header>
              {definition.overdue && <div className="lark-time-fields"><label className="lark-field"><span>首次超时阈值</span><div><input type="number" min="1" max="720" step="1" value={draft.thresholdHours} disabled={rulesBusy} onChange={(event) => updateRuleDraft(definition.eventType, { thresholdHours: event.target.value })} /><i>小时</i></div></label><label className="lark-field"><span>重复提醒间隔</span><div><input type="number" min="1" max="720" step="1" value={draft.repeatIntervalHours} disabled={rulesBusy} onChange={(event) => updateRuleDraft(definition.eventType, { repeatIntervalHours: event.target.value })} /><i>小时</i></div></label><label className="lark-field"><span>最大重复次数</span><div><input type="number" min="1" max="100" step="1" value={draft.maxRepeatCount} disabled={rulesBusy} onChange={(event) => updateRuleDraft(definition.eventType, { maxRepeatCount: event.target.value })} /><i>次</i></div></label></div>}
              {definition.groupOnly ? <div className="lark-group-only"><BellRing size={15} /><span>仅群通知，不 @ 人员</span></div> : <fieldset className="lark-rule-recipients"><legend>@指定人员</legend><div><label><input type="checkbox" disabled={rulesBusy} checked={draft.mentionAll} onChange={(event) => updateRuleDraft(definition.eventType, { mentionAll: event.target.checked })} /><span>所有人</span></label>{recipients.map((recipient) => {
                const selected = draft.recipientIds.includes(recipient.id)
                return <label className={[!recipient.enabled ? 'disabled' : '', draft.mentionAll ? 'locked-by-all' : ''].filter(Boolean).join(' ')} key={recipient.id}><input type="checkbox" disabled={rulesBusy || draft.mentionAll || (!recipient.enabled && !selected)} checked={!draft.mentionAll && selected} onChange={(event) => updateRuleDraft(definition.eventType, { recipientIds: event.target.checked ? [...draft.recipientIds, recipient.id] : draft.recipientIds.filter((id) => id !== recipient.id) })} /><span>{recipient.display_name || recipient.open_id_masked}</span></label>
              })}</div>{!recipients.length && <small>请先新增并启用通知人员</small>}</fieldset>}
              <footer><p className={`lark-field-error${validation ? ' visible' : ''}`} role={validation ? 'alert' : undefined}>{validation}</p></footer>
            </article>
          })}</div>
        </section>

        <section className="notification-section" aria-labelledby="lark-preview-title">
          <header className="notification-section-head"><div><h2 id="lark-preview-title">卡片预览</h2></div></header>
          <div className="lark-preview-layout"><div className="lark-preview-tabs" role="tablist" aria-label="通知场景">{ruleDefinitions.map((definition) => <button type="button" role="tab" aria-selected={selectedEvent === definition.eventType} className={selectedEvent === definition.eventType ? 'active' : ''} key={definition.eventType} onClick={() => setSelectedEvent(definition.eventType)}>{definition.title}<small>{definition.description}</small></button>)}</div><article className="lark-card-preview"><header><BellRing size={18} /><div><h3>{selectedDefinition.title}</h3><p>{selectedDefinition.subtitle(selectedRule.thresholdHours)}</p></div></header><dl><div><dt>@人员</dt><dd>{selectedDefinition.groupOnly ? '无（群通知）' : [selectedRule.mentionAll ? '@所有人' : '', ...previewRecipients.map((recipient) => recipient.display_name || recipient.open_id_masked)].filter(Boolean).join('、') || '未选择'}</dd></div><div><dt>客户名称</dt><dd>示例客户</dd></div><div><dt>域名</dt><dd>example.com</dd></div><div><dt>提交时间</dt><dd>2026-08-04 10:30</dd></div></dl><span className="lark-card-action">查看任务</span></article></div>
        </section>

        <section className={`notification-section recent${recentOpen ? ' open' : ''}`} aria-labelledby="lark-recent-title">
          <button className="lark-recent-trigger" type="button" aria-expanded={recentOpen} aria-controls="lark-recent-panel" onClick={() => setRecentOpen((open) => !open)}><span><Clock3 size={17} /><b id="lark-recent-title">最近发送状态</b><small>已发送只表示 Lark Webhook 已接受，不代表已读或已处理</small></span>{recentOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}</button>
          {recentOpen && <div id="lark-recent-panel" className="lark-recent-panel"><div className="lark-recent-filters" role="group" aria-label="发送状态筛选">{([['all', '全部'], ['failed', '发送失败'], ['retrying', '重试中']] as const).map(([value, label]) => <button type="button" className={recentFilter === value ? 'active' : ''} aria-pressed={recentFilter === value} key={value} onClick={() => setRecentFilter(value)}>{label}</button>)}<button className="refresh" type="button" disabled={recentLoading} aria-label="刷新最近发送状态" title="刷新" onClick={() => void loadRecent()}><RefreshCw size={15} /></button></div>{recentLoading ? <p className="notification-empty">正在加载...</p> : recentError ? <p className="notification-empty error">{recentError}</p> : <div className="lark-recent-table-wrap"><table className="lark-recent-table"><thead><tr><th>时间</th><th>规则</th><th>通知方式</th><th>提醒序号</th><th>状态</th><th>任务</th></tr></thead><tbody>{recentItems.map((item) => {
            const definition = ruleDefinitions.find((rule) => rule.eventType === item.event_type)
            const eventLabel = item.event_type === 'lark.test' ? '测试通知' : definition?.title ?? item.event_type
            return <tr key={item.id}><td data-label="时间">{formatTime(item.created_at)}</td><td data-label="规则"><b>{eventLabel}</b>{item.error_summary && <small>{item.error_summary}</small>}</td><td data-label="通知方式">{item.notification_mode === 'mention' ? '@ 指定人员' : '仅群通知'}</td><td data-label="提醒序号">{item.event_type === 'lark.test' ? '-' : item.reminder_index === 0 ? '首次' : `第 ${item.reminder_index} 次重复`}</td><td data-label="状态"><span className={`notification-status ${item.status}`}>{statusLabels[item.status]}</span></td><td data-label="任务">{item.task_id ? <Link to={`/admin/tasks?task_id=${encodeURIComponent(item.task_id)}`}>查看任务</Link> : '-'}</td></tr>
          })}</tbody></table>{!recentItems.length && <p className="notification-empty">暂无符合条件的发送状态</p>}</div>}</div>}
        </section>
      </>}
      {recipientDialog && <RecipientDialog recipient={recipientDialog === 'new' ? null : recipientDialog} busy={recipientBusy} onClose={() => setRecipientDialog(null)} onSave={saveRecipient} />}
      {testOpen && <TestDialog recipients={recipients} busy={testBusy} onClose={() => setTestOpen(false)} onConfirm={testNotification} />}
    </main>
  </div>
}
