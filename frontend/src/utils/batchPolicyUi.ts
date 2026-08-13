import type { BatchPolicyPayloadDto, BatchPromptTemplateDto } from '../types/modelStrategy'

const templateVariablePattern = /{{\s*([^{}]+?)\s*}}/g
export const BATCH_GENERATION_COUNT_OPTIONS = [3, 6, 9] as const
export const MAX_TOTAL_BATCH_GENERATION_COUNT = 9

function variableNames(value: string | null): string[] {
  if (!value) return []
  return [...value.matchAll(templateVariablePattern)].map((match) => match[1].trim())
}

/**
 * This is presentation-only gating. The server validates referenced asset ownership,
 * verified capabilities, variables, and publication atomically.
 */
export function isCompleteBatchTemplate(template: BatchPromptTemplateDto): boolean {
  const positiveVariables = variableNames(template.positive_prompt)
  const negativeVariables = variableNames(template.negative_prompt)
  return Boolean(
    template.name.trim()
      && template.positive_prompt.trim()
      && positiveVariables.filter((name) => name === '域名').length === 1
      && positiveVariables.filter((name) => name === '用户参考要求').length <= 1
      && [...positiveVariables, ...negativeVariables].every((name) => name === '域名' || name === '用户参考要求'),
  )
}

export function canSelectBatchGenerationCount(
  policy: BatchPolicyPayloadDto,
  styleId: string,
  count: number,
): boolean {
  const total = policy.styles.reduce(
    (sum, style) => sum + (style.id === styleId ? count : style.generation_count),
    0,
  )
  return total <= MAX_TOTAL_BATCH_GENERATION_COUNT
}

export function applyBatchGenerationCountGates(policy: BatchPolicyPayloadDto): BatchPolicyPayloadDto {
  return {
    ...policy,
    styles: policy.styles.map((style) => ({
      ...style,
      generation_count: style.templates.some(isCompleteBatchTemplate)
        ? Math.min(MAX_TOTAL_BATCH_GENERATION_COUNT, Math.max(0, Math.floor(style.generation_count)))
        : 0,
    })),
  }
}

export function visibleBatchTemplates(
  templates: BatchPromptTemplateDto[],
  expanded: boolean,
): BatchPromptTemplateDto[] {
  return templates.length > 3 && !expanded ? templates.slice(0, 3) : templates
}
