import { LoaderCircle, Send } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { ModelStrategyShell } from '../components/ModelStrategyShell'
import {
  getSingleImageEditPolicy,
  publishSingleImageEditPolicy,
  SingleImageEditPolicyServiceError,
} from '../services/singleImageEditPolicyService'
import { getModelConnections } from '../services/modelConnectionsService'
import { useToastStore } from '../stores/useToastStore'
import type {
  ModelConnectionDto,
  SingleImageEditPolicyPayloadDto,
  StrategyValidationErrorDto,
} from '../types/modelStrategy'

export function SingleEditPolicyPage() {
  const showToast = useToastStore((state) => state.showToast)
  const [draft, setDraft] = useState<SingleImageEditPolicyPayloadDto | null>(null)
  const [connections, setConnections] = useState<ModelConnectionDto[]>([])
  const [publishErrors, setPublishErrors] = useState<StrategyValidationErrorDto[]>([])
  const [isPublishing, setIsPublishing] = useState(false)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [policy, modelConnections] = await Promise.all([
          getSingleImageEditPolicy(),
          getModelConnections(),
        ])
        if (!active) return
        setDraft(policy.draft_seed)
        setConnections(modelConnections)
      } catch (error) {
        if (active) setLoadError(error instanceof Error ? error.message : '读取单图编辑策略失败')
      }
    }
    void load()
    return () => { active = false }
  }, [])

  const verifiedConnections = useMemo(() => connections.filter((connection) => connection.verified_capabilities.some((capability) => capability.capability === 'image_to_image' && capability.verified)), [connections])

  const publish = async () => {
    if (!draft || isPublishing) return
    setIsPublishing(true)
    setPublishErrors([])
    try {
      await publishSingleImageEditPolicy(draft)
      const policy = await getSingleImageEditPolicy()
      setDraft(policy.draft_seed)
      showToast('已按当前配置策略发布')
    } catch (error) {
      setPublishErrors(error instanceof SingleImageEditPolicyServiceError ? error.validationErrors : [])
      showToast(error instanceof Error ? error.message : '发布失败')
      window.setTimeout(() => document.querySelector<HTMLElement>('.single-policy-field.has-error, .scene-model-field.has-error')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 0)
    } finally {
      setIsPublishing(false)
    }
  }

  if (!draft) return <ModelStrategyShell title="单图编辑" description="以用户发起生成时正在查看的当前版本图为唯一源图。"><p className="strategy-loading">{loadError || '正在加载...'}</p></ModelStrategyShell>

  const fieldHasError = (field: string) => publishErrors.some((error) => error.field === field)

  return (
    <ModelStrategyShell
      title="单图编辑"
      description="以用户发起生成时正在查看的当前版本图为唯一源图，按修改指令执行差量编辑。"
    >
      <section className={`scene-model-field${fieldHasError('model_connection_id') ? ' has-error' : ''}`}>
        <div><span>单图编辑应用模型</span><p>只列出已验证图生图能力的连接；该选择独立于批量生图。</p></div>
        <label><span className="sr-only">选择单图编辑应用模型</span><select value={draft.model_connection_id} onChange={(event) => { setDraft({ ...draft, model_connection_id: event.target.value }); setPublishErrors([]) }}>
          <option value="">请选择已验证连接</option>
          {verifiedConnections.map((connection) => <option value={connection.id} key={connection.id}>{connection.provider} / {connection.model_id} · 已验证</option>)}
        </select></label>
      </section>

      {publishErrors.length > 0 && <div className="strategy-publish-errors" role="alert"><b>本次未发布，仍有 {publishErrors.length} 项需要处理。</b><p>{publishErrors[0].message}。请检查对应配置字段。</p></div>}

      <section className="single-policy-editor">
          <header className="strategy-section-title"><div><h2>Prompt 结构</h2><p>页面只维护业务语义，不暴露供应商私有请求参数。</p></div><button className="internal-button primary strategy-button-with-icon" type="button" disabled={isPublishing} onClick={() => void publish()}>{isPublishing ? <LoaderCircle className="strategy-spin" size={16} /> : <Send size={16} />}{isPublishing ? '正在发布...' : '发布'}</button></header>
          <div className="single-policy-fields">
            <label className={`single-policy-field${fieldHasError('positive_content') ? ' has-error' : ''}`}><span>正向内容 <b>*</b></span><textarea value={draft.positive_content} onChange={(event) => { setDraft({ ...draft, positive_content: event.target.value }); setPublishErrors([]) }} placeholder="描述编辑要求，并在合适位置加入 {{用户修改指令}}" /><small>必须且只能包含变量 <code>{'{{用户修改指令}}'}</code>，系统会在请求时替换为客户本轮指令。</small></label>
            <label className={`single-policy-field${fieldHasError('negative_avoidance') ? ' has-error' : ''}`}><span>负向避免项（选填）</span><textarea value={draft.negative_avoidance} onChange={(event) => { setDraft({ ...draft, negative_avoidance: event.target.value }); setPublishErrors([]) }} placeholder="如：避免改变品牌文字或增加无关元素" /></label>
          </div>
      </section>

    </ModelStrategyShell>
  )
}
