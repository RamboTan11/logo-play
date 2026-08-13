import axios from 'axios'
import { AlertTriangle, LoaderCircle, Pencil, PlugZap, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { ModelStrategyShell } from '../components/ModelStrategyShell'
import { StrategyDialog } from '../components/StrategyDialog'
import {
  createModelConnection,
  deleteModelConnection,
  getModelConnections,
  isMockModelConnections,
  testModelConnection,
  updateModelConnection,
} from '../services/modelConnectionsService'
import { useToastStore } from '../stores/useToastStore'
import type { ModelConnectionDto } from '../types/modelStrategy'

interface ConnectionFormState {
  id: string | null
  provider: string
  modelId: string
  apiUrl: string
  regionOrWorkspace: string
  apiKey: string
  apiKeyMasked: string | null
}

function connectionForm(connection?: ModelConnectionDto): ConnectionFormState {
  return {
    id: connection?.id ?? null,
    provider: connection?.provider ?? '',
    modelId: connection?.model_id ?? '',
    apiUrl: connection?.api_url ?? '',
    regionOrWorkspace: connection?.region_or_workspace ?? '',
    apiKey: '',
    apiKeyMasked: connection?.api_key_masked ?? null,
  }
}

function localizedTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function connectionTestMessage(result: Awaited<ReturnType<typeof testModelConnection>>): string {
  const status = result.provider_http_status ? `（上游 HTTP ${result.provider_http_status}）` : ''
  if (result.result === 'fallback_unverified') {
    return '未发起真实请求：请确认 API Key 和模型 ID 已保存，并检查服务端是否启用真实连通性测试。'
  }
  if (result.result === 'failed') return `连通性测试失败${status}：${result.message}`
  return `${result.message}${status}`
}

function connectionTestErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && error.code === 'ECONNABORTED') {
    return '连通性测试等待超时。服务端可能仍在完成本次测试，请稍后刷新列表确认最终状态。'
  }
  return error instanceof Error ? error.message : '连接测试失败'
}

function connectionDeleteErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error) && error.response?.status === 409) {
    return '该模型连接正在被当前生效策略使用。请先替换模型并发布策略后再删除。'
  }
  return error instanceof Error ? error.message : '删除模型连接失败'
}

export function ModelConnectionsPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [connections, setConnections] = useState<ModelConnectionDto[]>([])
  const [form, setForm] = useState<ConnectionFormState | null>(null)
  const [formError, setFormError] = useState('')
  const [testingId, setTestingId] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [connectionPendingRemoval, setConnectionPendingRemoval] = useState<ModelConnectionDto | null>(null)
  const [isRemoving, setIsRemoving] = useState(false)

  const refresh = async () => setConnections(await getModelConnections())
  useEffect(() => { void getModelConnections().then(setConnections) }, [])

  const saveConnection = async () => {
    if (!form || isSaving) return
    setFormError('')
    if (!form.provider.trim() || !form.modelId.trim() || !form.apiUrl.trim() || (!form.id && !form.apiKey.trim())) {
      setFormError('请完整填写服务提供方、模型 ID、API 地址和 API Key。')
      return
    }
    setIsSaving(true)
    try {
      if (form.id) {
        await updateModelConnection(form.id, {
          provider: form.provider,
          model_id: form.modelId,
          api_url: form.apiUrl,
          region_or_workspace: form.regionOrWorkspace || null,
          ...(form.apiKey.trim() ? { api_key: form.apiKey } : {}),
        })
        showToast(`连接配置已更新，请重新执行${isMockModelConnections() ? ' Mock' : ''}连通性测试`)
      } else {
        await createModelConnection({
          provider: form.provider,
          model_id: form.modelId,
          api_url: form.apiUrl,
          region_or_workspace: form.regionOrWorkspace || null,
          api_key: form.apiKey,
        })
        showToast(`模型连接已新增，完成${isMockModelConnections() ? ' Mock' : ''}测试后才可用于场景`)
      }
      setForm(null)
      await refresh()
    } catch (error) {
      setFormError(error instanceof Error ? error.message : '保存模型连接失败')
    } finally {
      setIsSaving(false)
    }
  }

  const testConnection = async (id: string) => {
    if (testingId) return
    setTestingId(id)
    try {
      const result = await testModelConnection(id)
      showToast(connectionTestMessage(result))
      await refresh()
    } catch (error) {
      showToast(connectionTestErrorMessage(error))
    } finally {
      setTestingId(null)
    }
  }

  const removeConnection = async () => {
    if (!connectionPendingRemoval || isRemoving) return
    setIsRemoving(true)
    try {
      await deleteModelConnection(connectionPendingRemoval.id)
      showToast('模型连接已退役')
      setConnectionPendingRemoval(null)
      await refresh()
    } catch (error) {
      showToast(connectionDeleteErrorMessage(error))
    } finally {
      setIsRemoving(false)
    }
  }

  return (
    <ModelStrategyShell
      title="模型列表"
      description="只维护模型连接；运行模型由各业务场景独立选择。"
      actions={<button className="internal-button primary strategy-button-with-icon" type="button" onClick={() => { setForm(connectionForm()); setFormError('') }}><Plus size={16} />新增模型连接</button>}
    >
      {isMockModelConnections() && <div className="mock-scope-notice"><PlugZap size={16} aria-hidden="true" /><span><b>当前为 Mock 连通性测试。</b> 页面不会调用真实 Seedream，也不会回显或记录 API Key 原文。</span></div>}
      <section className="model-connection-list" aria-label="模型连接列表">
        <header className="strategy-section-title"><div><h2>模型连接</h2><p>测试连通性后，符合图生图条件的连接可在批量和单图场景中选择。</p></div><span>{connections.length} 个连接</span></header>
        <div className="model-connection-table-wrap">
          <table className="model-connection-table">
            <thead><tr><th>服务与模型</th><th>API 请求地址</th><th>地域 / 工作空间</th><th>连通性</th><th><span className="sr-only">操作</span></th></tr></thead>
            <tbody>
              {connections.map((connection) => {
                const connectivity = connection.connection_status === 'verified'
                  ? { label: '已连通', tone: 'connected' }
                  : connection.connection_status === 'mock_verified'
                    ? { label: 'Mock 已连通', tone: 'connected' }
                    : connection.connection_status === 'failed' || connection.connection_status === 'mock_failed'
                    ? { label: '连通失败', tone: 'failed' }
                    : connection.connection_status === 'fallback_unverified'
                      ? { label: '未验证', tone: 'untested' }
                    : { label: '未测试', tone: 'untested' }
                return <tr key={connection.id}>
                  <td><b>{connection.provider}</b><span className="model-code">{connection.model_id}</span><small>连接版本 V{connection.version} · {localizedTime(connection.updated_at)}</small></td>
                  <td><span className="model-endpoint-copy">{connection.api_url}</span></td>
                  <td>{connection.region_or_workspace ?? '-'}</td>
                  <td><span className={`model-connectivity ${connectivity.tone}`}>{connectivity.label}</span></td>
                  <td><div className="strategy-row-actions">
                    <button className="strategy-icon-button" type="button" title="测试连通性" aria-label={`测试连通性 ${connection.model_id}`} disabled={testingId !== null} onClick={() => void testConnection(connection.id)}>{testingId === connection.id ? <LoaderCircle className="strategy-spin" size={16} /> : <PlugZap size={16} />}</button>
                    <button className="strategy-icon-button" type="button" title="编辑连接" aria-label={`编辑连接 ${connection.model_id}`} onClick={() => { setForm(connectionForm(connection)); setFormError('') }}><Pencil size={16} /></button>
                    <button className="strategy-icon-button danger" type="button" title="删除连接" aria-label={`删除连接 ${connection.model_id}`} onClick={() => setConnectionPendingRemoval(connection)}><Trash2 size={16} /></button>
                  </div></td>
                </tr>
              })}
            </tbody>
          </table>
        </div>
      </section>
      {form && <StrategyDialog
        title={form.id ? '编辑模型连接' : '新增模型连接'}
        description={form.id ? `已有 API Key 不会回显；留空表示保持原密钥。修改后需重新执行${isMockModelConnections() ? ' Mock' : ''}连通性测试。` : `先保存连接，再执行${isMockModelConnections() ? ' Mock' : ''}连通性测试。`}
        onClose={() => setForm(null)}
        footer={<><button className="internal-button" type="button" onClick={() => setForm(null)}>取消</button><button className="internal-button primary" type="button" disabled={isSaving} onClick={() => void saveConnection()}>{isSaving ? '处理中...' : form.id ? '更新连接' : '新增连接'}</button></>}
      >
        <form className="strategy-form" onSubmit={(event) => { event.preventDefault(); void saveConnection() }}>
          <label><span>服务提供方 <b>*</b></span><input value={form.provider} onChange={(event) => setForm({ ...form, provider: event.target.value })} placeholder="如：火山方舟" /></label>
          <label><span>模型 ID <b>*</b></span><input value={form.modelId} onChange={(event) => setForm({ ...form, modelId: event.target.value })} placeholder="填写目标账号中的实际模型 ID" /></label>
          <label className="strategy-form-wide"><span>API 请求地址 <b>*</b></span><input type="url" value={form.apiUrl} onChange={(event) => setForm({ ...form, apiUrl: event.target.value })} placeholder="https://..." /></label>
          <label><span>地域 / 工作空间</span><input value={form.regionOrWorkspace} onChange={(event) => setForm({ ...form, regionOrWorkspace: event.target.value })} placeholder="供应商需要时填写" /></label>
          <label><span>{form.id ? '替换 API Key' : 'API Key'} {!form.id && <b>*</b>}</span>{form.id && <small>当前 API Key：{form.apiKeyMasked ?? '未配置'}；留空不修改，输入新值替换。</small>}<input type="password" autoComplete="new-password" value={form.apiKey} onChange={(event) => setForm({ ...form, apiKey: event.target.value })} placeholder={form.id ? '留空不修改，输入新值替换' : '仅写入，不回显'} /></label>
          {formError && <p className="strategy-form-error strategy-form-wide" role="alert">{formError}</p>}
        </form>
      </StrategyDialog>}
      {connectionPendingRemoval && <StrategyDialog
        title="退役模型连接"
        variant="confirmation"
        onClose={() => { if (!isRemoving) setConnectionPendingRemoval(null) }}
        footer={<><button className="internal-button" type="button" disabled={isRemoving} onClick={() => setConnectionPendingRemoval(null)}>取消</button><button className="internal-button danger" type="button" disabled={isRemoving} onClick={() => void removeConnection()}>{isRemoving ? '正在退役...' : '确认退役'}</button></>}
      >
        <div className="strategy-confirmation-notice">
          <AlertTriangle size={20} aria-hidden="true" />
          <div><b>连接将从后续策略中移除</b><p>“{connectionPendingRemoval.model_id}”将不再用于新策略；历史策略与生成记录仍可追溯。</p></div>
        </div>
      </StrategyDialog>}
    </ModelStrategyShell>
  )
}
