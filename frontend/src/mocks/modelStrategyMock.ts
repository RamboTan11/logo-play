import type {
  BatchPolicyDataDto,
  BatchPolicyPayloadDto,
  BatchPolicyVersionDto,
  BatchPromptTemplateDto,
  CreateModelConnectionRequest,
  ModelConnectionDto,
  PolicyPublishedDto,
  ReferenceImageAssetDto,
  SingleImageEditPolicyDataDto,
  SingleImageEditPolicyPayloadDto,
  SingleImageEditPolicyVersionDto,
  StrategyValidationErrorDto,
  TestModelConnectionData,
  UpdateModelConnectionRequest,
} from '../types/modelStrategy'

const templateVariablePattern = /{{\s*([^{}]+?)\s*}}/g

interface InternalModelConnection extends Omit<ModelConnectionDto, 'api_key_masked'> {
  apiKeySecret: string | null
}

interface CompileContext {
  connections: ModelConnectionDto[]
  assets: ReferenceImageAssetDto[]
}

export class ModelStrategyMockError extends Error {
  readonly validationErrors: StrategyValidationErrorDto[]

  constructor(message: string, validationErrors: StrategyValidationErrorDto[] = []) {
    super(message)
    this.name = 'ModelStrategyMockError'
    this.validationErrors = validationErrors
  }
}

function clone<T>(value: T): T {
  return structuredClone(value)
}

function isoNow(): string {
  return new Date().toISOString()
}

function publicConnection(connection: InternalModelConnection): ModelConnectionDto {
  return clone({
    id: connection.id,
    provider: connection.provider,
    model_id: connection.model_id,
    api_url: connection.api_url,
    region_or_workspace: connection.region_or_workspace,
    credential_status: connection.credential_status,
    api_key_masked: connection.apiKeySecret ? maskApiKey(connection.apiKeySecret) : null,
    connection_status: connection.connection_status,
    verified_capabilities: connection.verified_capabilities,
    version: connection.version,
    updated_at: connection.updated_at,
  })
}

function maskApiKey(apiKey: string): string {
  return apiKey.length > 6 ? `${apiKey.slice(0, 3)}******${apiKey.slice(-3)}` : '******'
}

function normalizedVariableNames(value: string): string[] {
  return [...value.matchAll(templateVariablePattern)].map((match) => match[1].trim())
}

function variableErrors(value: string | null, field: string, allowedVariables: ReadonlySet<string>): StrategyValidationErrorDto[] {
  if (!value) return []
  return normalizedVariableNames(value)
    .filter((name) => !allowedVariables.has(name))
    .map((name) => ({
      field,
      code: 'unknown_template_variable',
      message: `不支持变量 {{${name}}}`,
    }))
}

function modelConnectionError(modelConnectionId: string, context: CompileContext): StrategyValidationErrorDto[] {
  const connection = context.connections.find((item) => item.id === modelConnectionId)
  const imageToImageVerified = connection?.verified_capabilities.some((item) => item.capability === 'image_to_image' && item.verified)
  if (connection && imageToImageVerified) return []
  return [{
    field: 'model_connection_id',
    code: 'unverified_model_connection',
    message: '请选择已通过 Mock 图生图能力测试的模型连接',
  }]
}

function batchTemplateErrors(
  template: BatchPromptTemplateDto,
  fieldPrefix: string,
  context: CompileContext,
): StrategyValidationErrorDto[] {
  const errors: StrategyValidationErrorDto[] = []
  if (!template.name.trim()) errors.push({ field: `${fieldPrefix}.name`, code: 'required', message: '请填写模板名称' })
  if (template.reference_images.length > 8) errors.push({ field: `${fieldPrefix}.reference_images`, code: 'invalid_reference_image', message: '参考图最多支持 8 张' })
  if (new Set(template.reference_images).size !== template.reference_images.length) errors.push({ field: `${fieldPrefix}.reference_images`, code: 'invalid_reference_image', message: '参考图不能重复' })
  template.reference_images.forEach((assetId, index) => {
    if (!context.assets.some((asset) => asset.id === assetId)) errors.push({ field: `${fieldPrefix}.reference_images[${index}]`, code: 'invalid_reference_image', message: '参考图资产无效，请重新上传' })
  })
  if (!template.positive_prompt.trim()) {
    errors.push({ field: `${fieldPrefix}.positive_prompt`, code: 'required', message: '请填写正提示词' })
  } else if (!normalizedVariableNames(template.positive_prompt).includes('域名')) {
    errors.push({ field: `${fieldPrefix}.positive_prompt`, code: 'required_template_variable', message: '正提示词必须包含 {{域名}}' })
  }
  errors.push(...variableErrors(template.positive_prompt, `${fieldPrefix}.positive_prompt`, new Set(['域名', '用户参考要求'])))
  for (const variableName of ['域名', '用户参考要求'] as const) {
    const count = normalizedVariableNames(template.positive_prompt).filter((name) => name === variableName).length
    if (count > 1) errors.push({ field: `${fieldPrefix}.positive_prompt`, code: 'unknown_template_variable', message: `正提示词中的 {{${variableName}}} 出现了 ${count} 次，同一变量最多只能出现一次` })
  }
  errors.push(...variableErrors(template.negative_prompt, `${fieldPrefix}.negative_prompt`, new Set(['域名'])))
  return errors
}

export function isCompleteBatchTemplate(template: BatchPromptTemplateDto): boolean {
  return Boolean(
    template.name.trim()
      && template.positive_prompt.trim()
      && normalizedVariableNames(template.positive_prompt).filter((name) => name === '域名').length === 1
      && normalizedVariableNames(template.positive_prompt).filter((name) => name === '用户参考要求').length <= 1
      && !variableErrors(template.positive_prompt, '', new Set(['域名', '用户参考要求'])).length
      && !variableErrors(template.negative_prompt, '', new Set(['域名'])).length,
  )
}

export function normalizeBatchGenerationGates(policy: BatchPolicyPayloadDto): BatchPolicyPayloadDto {
  return {
    ...policy,
    styles: policy.styles.map((style) => ({
      ...style,
      generation_count: style.templates.some(isCompleteBatchTemplate) ? Math.min(9, Math.max(0, Math.floor(style.generation_count))) : 0,
    })),
  }
}

export function validateBatchPolicy(policy: BatchPolicyPayloadDto, context: CompileContext): StrategyValidationErrorDto[] {
  const errors = modelConnectionError(policy.model_connection_id, context)
  if (!policy.styles.length) errors.push({ field: 'styles', code: 'required', message: '请至少新增一个风格类型' })
  policy.styles.forEach((style, styleIndex) => {
    const stylePrefix = `styles[${styleIndex}]`
    if (!style.name.trim()) errors.push({ field: `${stylePrefix}.name`, code: 'required', message: '请填写风格名称' })
    style.templates.forEach((template, templateIndex) => {
      errors.push(...batchTemplateErrors(template, `${stylePrefix}.templates[${templateIndex}]`, context))
    })
    if (style.generation_count > 0 && !style.templates.some(isCompleteBatchTemplate)) {
      errors.push({ field: `${stylePrefix}.generation_count`, code: 'required', message: '创建完整模板后才可设置生成数' })
    }
  })
  const totalGenerationCount = policy.styles.reduce((sum, style) => sum + style.generation_count, 0)
  if (totalGenerationCount > 9) {
    errors.push({ field: 'styles', code: 'invalid_generation_count', message: `所有风格本轮合计最多生成 9 张图片，当前为 ${totalGenerationCount} 张` })
  }
  return errors
}

export function validateSingleEditPolicy(
  policy: SingleImageEditPolicyPayloadDto,
  context: CompileContext,
): StrategyValidationErrorDto[] {
  const errors = modelConnectionError(policy.model_connection_id, context)
  if (!policy.positive_content.trim()) errors.push({ field: 'positive_content', code: 'required', message: '请填写正向内容' })
  if (policy.positive_content.trim() && !normalizedVariableNames(policy.positive_content).includes('用户补充描述')) {
    errors.push({ field: 'positive_content', code: 'required_template_variable', message: '正向内容必须包含 {{用户补充描述}}' })
  }
  errors.push(...variableErrors(policy.positive_content, 'positive_content', new Set(['用户补充描述'])))
  errors.push(...variableErrors(policy.negative_avoidance, 'negative_avoidance', new Set()))
  return errors
}

const seededAt = '2026-07-29T02:30:00.000Z'
let connectionSequence = 3
let assetSequence = 2
let batchVersionSequence = 1
let singleVersionSequence = 1

let connections: InternalModelConnection[] = [
  {
    id: 'mock-model-001',
    provider: '火山方舟（Mock）',
    model_id: 'seedream-4.0-mock-primary',
    api_url: 'https://ark.cn-beijing.volces.com/api/v3/images/generations',
    region_or_workspace: 'cn-beijing / mock-workspace-a',
    credential_status: 'configured',
    connection_status: 'mock_verified',
    verified_capabilities: [{ capability: 'image_to_image', verified: true, verification_mode: 'mock', verified_at: seededAt }],
    version: 1,
    updated_at: seededAt,
    apiKeySecret: 'mock-secret-not-returned',
  },
  {
    id: 'mock-model-002',
    provider: '火山方舟（Mock）',
    model_id: 'seedream-4.0-mock-backup',
    api_url: 'https://ark.cn-beijing.volces.com/api/v3/images/generations',
    region_or_workspace: 'cn-beijing / mock-workspace-b',
    credential_status: 'configured',
    connection_status: 'mock_verified',
    verified_capabilities: [{ capability: 'image_to_image', verified: true, verification_mode: 'mock', verified_at: seededAt }],
    version: 1,
    updated_at: seededAt,
    apiKeySecret: 'mock-secret-not-returned',
  },
  {
    id: 'mock-model-003',
    provider: '测试连接（Mock）',
    model_id: 'unverified-image-model',
    api_url: 'https://example.invalid/mock/images',
    region_or_workspace: null,
    credential_status: 'missing',
    connection_status: 'untested',
    verified_capabilities: [],
    version: 1,
    updated_at: seededAt,
    apiKeySecret: null,
  },
]

const assets: ReferenceImageAssetDto[] = [
  {
    id: 'mock-reference-asset-001',
    filename: 'geometric-order-reference.png',
    mime_type: 'image/png',
    size_bytes: 1832,
    content_hash: 'mock-sha256-geometric-order-v1',
    version: 1,
    created_at: seededAt,
  },
  {
    id: 'mock-reference-asset-002',
    filename: 'kinetic-symbol-reference.png',
    mime_type: 'image/png',
    size_bytes: 1764,
    content_hash: 'mock-sha256-kinetic-symbol-v1',
    version: 1,
    created_at: seededAt,
  },
]

const seededReferencePng = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
const referenceImageContents = new Map<string, Blob>([
  ['mock-reference-asset-001', pngBlob(seededReferencePng)],
  ['mock-reference-asset-002', pngBlob(seededReferencePng)],
])

let batchVersions: BatchPolicyVersionDto[] = [{
  id: 'mock-batch-policy-v1',
  version: 1,
  model_connection_id: 'mock-model-001',
  styles_snapshot: [{
    id: 'mock-style-001',
    name: '极简科技',
    generation_count: 3,
    templates: [{
      id: 'mock-template-001',
      name: '几何秩序',
      reference_images: ['mock-reference-asset-001'],
      positive_prompt: '为 {{域名}} 设计克制、精确、具有高级数字品牌感的几何 Logo。',
      negative_prompt: '避免复杂插画、低清晰度、冗余文字、水印。',
    }],
  }, {
    id: 'mock-style-002',
    name: '未来娱乐',
    generation_count: 3,
    templates: [{
      id: 'mock-template-002',
      name: '动感符号',
      reference_images: ['mock-reference-asset-002'],
      positive_prompt: '为 {{域名}} 设计具有受控动势和清晰轮廓的未来娱乐品牌 Logo。',
      negative_prompt: '',
    }],
  }],
  published_at: seededAt,
}]
let activeBatchVersionId = 'mock-batch-policy-v1'
let batchDraft: BatchPolicyPayloadDto | null = null
let batchDraftUpdatedAt: string | null = null

let singleVersions: SingleImageEditPolicyVersionDto[] = [{
  id: 'mock-single-policy-v1',
  version: 1,
  model_connection_id: 'mock-model-002',
  positive_content: '保留原图的核心识别特征，优化结构、比例、边缘和视觉完成度。根据用户本轮补充要求进行调整：{{用户补充描述}}',
  negative_avoidance: '避免改变品牌文字、增加无关元素或降低图形清晰度。',
  published_at: seededAt,
}]
let activeSingleVersionId = 'mock-single-policy-v1'

function compileContext(): CompileContext {
  return { connections: connections.map(publicConnection), assets: clone(assets) }
}

function activeBatchVersion(): BatchPolicyVersionDto | null {
  return batchVersions.find((version) => version.id === activeBatchVersionId) ?? null
}

export function getActiveBatchGenerationTargetCountMock(): number {
  const active = activeBatchVersion()
  return active?.styles_snapshot.reduce((total, style) => total + style.generation_count, 0) ?? 0
}

function activeSingleVersion(): SingleImageEditPolicyVersionDto | null {
  return singleVersions.find((version) => version.id === activeSingleVersionId) ?? null
}

export async function getModelConnectionsMock(): Promise<ModelConnectionDto[]> {
  return connections.map(publicConnection)
}

export async function createModelConnectionMock(request: CreateModelConnectionRequest): Promise<ModelConnectionDto> {
  if (!request.provider.trim() || !request.model_id.trim() || !request.api_url.trim() || !request.api_key.trim()) {
    throw new ModelStrategyMockError('请完整填写模型连接必填项')
  }
  connectionSequence += 1
  const timestamp = isoNow()
  const connection: InternalModelConnection = {
    id: `mock-model-${String(connectionSequence).padStart(3, '0')}`,
    provider: request.provider.trim(),
    model_id: request.model_id.trim(),
    api_url: request.api_url.trim(),
    region_or_workspace: request.region_or_workspace?.trim() || null,
    credential_status: 'configured',
    connection_status: 'untested',
    verified_capabilities: [],
    version: 1,
    updated_at: timestamp,
    apiKeySecret: request.api_key,
  }
  connections = [...connections, connection]
  return publicConnection(connection)
}

export async function updateModelConnectionMock(id: string, request: UpdateModelConnectionRequest): Promise<ModelConnectionDto> {
  const connection = connections.find((item) => item.id === id)
  if (!connection) throw new ModelStrategyMockError('模型连接不存在')
  if (!request.provider.trim() || !request.model_id.trim() || !request.api_url.trim()) {
    throw new ModelStrategyMockError('请完整填写模型连接必填项')
  }
  const updated: InternalModelConnection = {
    ...connection,
    provider: request.provider.trim(),
    model_id: request.model_id.trim(),
    api_url: request.api_url.trim(),
    region_or_workspace: request.region_or_workspace?.trim() || null,
    apiKeySecret: request.api_key?.trim() || connection.apiKeySecret,
    credential_status: request.api_key?.trim() || connection.apiKeySecret ? 'configured' : 'missing',
    connection_status: 'untested',
    verified_capabilities: [],
    version: connection.version + 1,
    updated_at: isoNow(),
  }
  connections = connections.map((item) => item.id === id ? updated : item)
  return publicConnection(updated)
}

export async function deleteModelConnectionMock(id: string): Promise<void> {
  if (activeBatchVersion()?.model_connection_id === id || activeSingleVersion()?.model_connection_id === id) {
    throw new ModelStrategyMockError('该模型连接正在被当前生效策略使用，请先替换模型并发布策略后再删除')
  }
  connections = connections.filter((connection) => connection.id !== id)
}

export async function testModelConnectionMock(id: string): Promise<TestModelConnectionData> {
  const connection = connections.find((item) => item.id === id)
  if (!connection) throw new ModelStrategyMockError('模型连接不存在')
  const passed = Boolean(connection.apiKeySecret)
  const updated: InternalModelConnection = {
    ...connection,
    connection_status: passed ? 'mock_verified' : 'mock_failed',
    verified_capabilities: passed
      ? [{ capability: 'image_to_image', verified: true, verification_mode: 'mock', verified_at: isoNow() }]
      : [],
    updated_at: isoNow(),
  }
  connections = connections.map((item) => item.id === id ? updated : item)
  return {
    connection: publicConnection(updated),
    result: passed ? 'mock_verified' : 'mock_failed',
    message: passed ? 'Mock 连通性测试通过；尚未调用真实 Seedream' : '连通性测试失败，请先写入或替换 API Key',
  }
}

async function fileHash(file: File): Promise<string> {
  const bytes = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, '0')).join('')
}

export async function uploadReferenceImageMock(file: File): Promise<ReferenceImageAssetDto> {
  if (!file.type.startsWith('image/')) throw new ModelStrategyMockError('仅支持上传图片文件')
  assetSequence += 1
  const contentHash = await fileHash(file)
  const asset: ReferenceImageAssetDto = {
    id: `mock-reference-asset-${String(assetSequence).padStart(3, '0')}`,
    filename: file.name,
    mime_type: file.type,
    size_bytes: file.size,
    content_hash: contentHash,
    version: 1,
    created_at: isoNow(),
  }
  assets.push(asset)
  referenceImageContents.set(asset.id, file.slice(0, file.size, file.type))
  return clone(asset)
}

export async function getReferenceImageContentMock(assetId: string): Promise<Blob> {
  const content = referenceImageContents.get(assetId)
  if (!content) throw new ModelStrategyMockError('参考图不存在')
  return content.slice(0, content.size, content.type)
}

export async function getReferenceImageAssetsMock(ids: string[] = []): Promise<ReferenceImageAssetDto[]> {
  const requested = [...new Set(ids.filter(Boolean))]
  const byId = new Map(assets.map((asset) => [asset.id, asset]))
  return requested.flatMap((id) => {
    const asset = byId.get(id)
    return asset ? [clone(asset)] : []
  })
}

export async function getBatchPolicyMock(): Promise<BatchPolicyDataDto> {
  const active = activeBatchVersion()
  return clone({
    draft_seed: batchDraft ?? (active
      ? { model_connection_id: active.model_connection_id, styles: active.styles_snapshot }
      : { model_connection_id: '', styles: [] }),
    last_published_at: active?.published_at ?? null,
    draft_updated_at: batchDraftUpdatedAt,
  })
}

export async function getBatchPolicyVersionsMock(): Promise<BatchPolicyVersionDto[]> {
  return clone([...batchVersions].reverse())
}

export async function saveBatchPolicyDraftMock(policy: BatchPolicyPayloadDto): Promise<{ draft_saved: true; saved_at: string }> {
  batchDraft = clone(policy)
  batchDraftUpdatedAt = isoNow()
  return { draft_saved: true, saved_at: batchDraftUpdatedAt }
}

export async function publishBatchPolicyMock(policy?: BatchPolicyPayloadDto): Promise<PolicyPublishedDto> {
  if (policy) await saveBatchPolicyDraftMock(policy)
  const draft = batchDraft ?? getBatchPolicyMockSync()
  const normalized = normalizeBatchGenerationGates(clone(draft))
  const errors = validateBatchPolicy(normalized, compileContext())
  if (errors.length) throw new ModelStrategyMockError('批量生图策略校验失败', errors)
  batchVersionSequence += 1
  const version: BatchPolicyVersionDto = clone({
    id: `mock-batch-policy-v${batchVersionSequence}`,
    version: batchVersionSequence,
    model_connection_id: normalized.model_connection_id,
    styles_snapshot: normalized.styles,
    published_at: isoNow(),
  })
  batchVersions = [...batchVersions, version]
  activeBatchVersionId = version.id
  return { published: true }
}

function getBatchPolicyMockSync(): BatchPolicyPayloadDto {
  const active = activeBatchVersion()
  return active
    ? { model_connection_id: active.model_connection_id, styles: active.styles_snapshot }
    : { model_connection_id: '', styles: [] }
}

export async function getSingleEditPolicyMock(): Promise<SingleImageEditPolicyDataDto> {
  const active = activeSingleVersion()
  return clone({
    draft_seed: active
      ? {
          model_connection_id: active.model_connection_id,
          positive_content: active.positive_content,
          negative_avoidance: active.negative_avoidance,
        }
      : { model_connection_id: '', positive_content: '', negative_avoidance: '' },
  })
}

export async function getSingleEditPolicyVersionsMock(): Promise<SingleImageEditPolicyVersionDto[]> {
  return clone([...singleVersions].reverse())
}

export async function publishSingleEditPolicyMock(
  policy: SingleImageEditPolicyPayloadDto,
): Promise<PolicyPublishedDto> {
  const errors = validateSingleEditPolicy(policy, compileContext())
  if (errors.length) throw new ModelStrategyMockError('单图编辑策略校验失败', errors)
  singleVersionSequence += 1
  const version: SingleImageEditPolicyVersionDto = clone({
    id: `mock-single-policy-v${singleVersionSequence}`,
    version: singleVersionSequence,
    ...policy,
    published_at: isoNow(),
  })
  singleVersions = [...singleVersions, version]
  activeSingleVersionId = version.id
  return { published: true }
}

function pngBlob(base64Value: string): Blob {
  const binary = atob(base64Value)
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0))
  return new Blob([bytes], { type: 'image/png' })
}
