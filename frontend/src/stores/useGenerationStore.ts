import { create } from 'zustand'
import type {
  BatchGenerationStatusData,
  DomainSuffix,
  GenerationBatch,
  GenerationStatusData,
} from '../types/api'
import {
  GenerationApiError,
  createBatchGeneration,
  getBatchGenerationStatus,
  getLatestSuccessfulGeneration,
  retryBatchGenerationSlot,
} from '../services/generationsService'
import { mergeRetriedBatchWindow, resolveSuccessfulBatchWindow } from '../utils/generationBatchWindow'
import {
  recoverInitialGeneration,
  resolveGenerationPollDisposition,
} from '../utils/generationRecovery'
import { createSingleFlightGate } from '../utils/singleFlight'
import { useToastStore } from './useToastStore'
import { clearGenerationSourceRecovery } from '../utils/generationSourceRecovery'

const activeGenerationStorageKey = 'logo-generated.active-generation'
const isMockMode = import.meta.env.VITE_USE_MOCK === 'true'
const slotRetryPollIntervalMs = 300
const slotRetryMaxPolls = 400

interface ActiveGeneration {
  requestId: string
  domain?: string
  domainLabel?: string
  domainSuffix?: DomainSuffix
  submittedAt?: number
  targetCount?: number
}

export interface CompletedGeneration {
  requestId: string
  domain: string
  domainLabel: string
  domainSuffix: DomainSuffix
  targetCount: number
}

interface GenerationState {
  domainLabel: string
  domainSuffix: DomainSuffix
  sourceImageAssetId: string | null
  userReferenceRequirement: string
  error: string | null
  requestId: string | null
  isProcessing: boolean
  isRegenerating: boolean
  completedGeneration: CompletedGeneration | null
  batchHistory: GenerationBatch[]
  activeBatchId: string | null
  isCompletedBatchesRestored: boolean
  shouldRedirectToResults: boolean
  setDomainLabel: (domainLabel: string) => void
  setDomainSuffix: (domainSuffix: DomainSuffix) => void
  retryingSlots: string[]
  retrySlot: (requestId: string, slotIndex: number, retryToken: string) => Promise<void>
  setSourceImageAssetId: (assetId: string | null) => void
  setUserReferenceRequirement: (requirement: string) => void
  clearSourceImage: () => void
  generate: () => Promise<void>
  regenerate: () => Promise<void>
  selectBatch: (requestId: string) => void
  restoreActiveGeneration: () => Promise<void>
  restoreCompletedBatches: () => Promise<void>
  returnToCreation: () => void
  clearCustomerState: () => void
}

function readActiveGeneration(): ActiveGeneration | null {
  if (typeof window === 'undefined') return null
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(activeGenerationStorageKey) ?? 'null')
    if (typeof parsed !== 'object' || parsed === null || !('request_id' in parsed)) return null
    if (typeof parsed.request_id !== 'string' || !parsed.request_id) return null
    if (!isMockMode) return { requestId: parsed.request_id }
    if (
      !('domain' in parsed)
      || !('domain_label' in parsed)
      || !('domain_suffix' in parsed)
      || !('submitted_at' in parsed)
      || !('target_count' in parsed)
      || typeof parsed.domain !== 'string'
      || typeof parsed.domain_label !== 'string'
      || !isDomainSuffix(parsed.domain_suffix)
      || typeof parsed.submitted_at !== 'number'
      || typeof parsed.target_count !== 'number'
    ) return null
    return {
      requestId: parsed.request_id,
      domain: parsed.domain,
      domainLabel: parsed.domain_label,
      domainSuffix: parsed.domain_suffix,
      submittedAt: parsed.submitted_at,
      targetCount: parsed.target_count,
    }
  } catch {
    window.localStorage.removeItem(activeGenerationStorageKey)
    return null
  }
}

function writeActiveGeneration(active: ActiveGeneration): void {
  if (typeof window === 'undefined') return
  if (!isMockMode) {
    window.localStorage.setItem(activeGenerationStorageKey, JSON.stringify({ request_id: active.requestId }))
    return
  }
  window.localStorage.setItem(activeGenerationStorageKey, JSON.stringify({
    request_id: active.requestId,
    domain: active.domain,
    domain_label: active.domainLabel,
    domain_suffix: active.domainSuffix,
    submitted_at: active.submittedAt,
    target_count: active.targetCount,
  }))
}

function clearActiveGeneration(): void {
  if (typeof window !== 'undefined') window.localStorage.removeItem(activeGenerationStorageKey)
}

function isDomainSuffix(value: unknown): value is DomainSuffix {
  return value === '.com' || value === '.game' || value === '.win' || value === '.app'
}

function isRealStatus(value: BatchGenerationStatusData | GenerationStatusData): value is BatchGenerationStatusData {
  return 'batches' in value
}

function batchCompletion(batch: GenerationBatch | undefined): CompletedGeneration | null {
  if (!batch) return null
  return {
    requestId: batch.request_id,
    domain: batch.domain,
    domainLabel: batch.domain_label,
    domainSuffix: batch.domain_suffix,
    targetCount: batch.target_count,
  }
}

function candidateFailureSignature(batch: GenerationBatch | undefined, slotIndex: number): string | null {
  const failure = batch?.candidates.find((candidate) => candidate.slot_index === slotIndex)?.failure
  return failure ? `${failure.code}:${failure.message}` : null
}

function waitForSlotRetryPoll(): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, slotRetryPollIntervalMs))
}

const initialActiveGeneration = readActiveGeneration()

export const useGenerationStore = create<GenerationState>((set, get) => {
  let recoverySequence = 0
  const regenerationGate = createSingleFlightGate()

  const poll = async (
    active: ActiveGeneration,
    phase: 'creation' | 'regeneration' | 'restore',
  ): Promise<'restored' | 'stale'> => {
    try {
      const response = await getBatchGenerationStatus(active.requestId, active.submittedAt ?? null)
      if (get().requestId !== active.requestId) return 'stale'

      if (isRealStatus(response)) {
        const isProcessing = response.status === 'processing'
        const disposition = resolveGenerationPollDisposition(response.status, phase)
        if (disposition.clearActiveRequest) clearActiveGeneration()
        if (disposition.restoreLatestSuccessful) {
          set({ requestId: null, isProcessing: false, isRegenerating: false })
          return 'stale'
        }
        const batchWindow = resolveSuccessfulBatchWindow(
          response.batches,
          get().activeBatchId,
          response.status === 'succeeded' ? response.request_id : null,
        )
        set({
          domainLabel: response.domain_label,
          domainSuffix: response.domain_suffix,
          requestId: isProcessing ? response.request_id : null,
          isProcessing: phase !== 'regeneration' && isProcessing,
          isRegenerating: phase === 'regeneration' && isProcessing,
          completedGeneration: batchCompletion(batchWindow.latestBatch ?? undefined),
          batchHistory: batchWindow.batches,
          activeBatchId: batchWindow.activeBatchId,
          isCompletedBatchesRestored: true,
          shouldRedirectToResults: disposition.shouldRedirectToResults,
          error: response.status === 'failed' ? '本批方案生成失败，请稍后重试。' : null,
        })
        if (isProcessing) {
          window.setTimeout(() => void poll(active, phase), 500)
        } else if (response.status === 'failed' && phase === 'regeneration') {
          useToastStore.getState().showToast('重新生成失败，已保留原有方案。')
        }
        return 'restored'
      }

      if (response.status === 'processing') {
        window.setTimeout(() => void poll(active, phase), 250)
        return 'restored'
      }
      clearActiveGeneration()
      if (response.status === 'failed') {
        if (phase === 'restore') {
          set({ requestId: null, isProcessing: false, isRegenerating: false })
          return 'stale'
        }
        set({
          requestId: null,
          isProcessing: false,
          isRegenerating: false,
          isCompletedBatchesRestored: true,
          shouldRedirectToResults: false,
          error: '本批方案生成失败，请稍后重试。',
        })
        if (phase === 'regeneration') useToastStore.getState().showToast('重新生成失败，已保留原有方案。')
        return 'restored'
      }

      const batch: GenerationBatch = {
        request_id: active.requestId,
        domain: active.domain ?? `${get().domainLabel}${get().domainSuffix}`,
        domain_label: active.domainLabel ?? get().domainLabel,
        domain_suffix: active.domainSuffix ?? get().domainSuffix,
        target_count: active.targetCount ?? 0,
        status: 'succeeded',
        created_at: new Date().toISOString(),
        logo_versions: [],
        candidates: [],
      }
      const prior = get().batchHistory.filter((item) => item.request_id !== batch.request_id).slice(-1)
      const disposition = resolveGenerationPollDisposition(response.status, phase)
      set({
        domainLabel: phase === 'restore' ? '' : batch.domain_label,
        domainSuffix: phase === 'restore' ? '.com' : batch.domain_suffix,
        requestId: null,
        isProcessing: false,
        isRegenerating: false,
        completedGeneration: batchCompletion(batch),
        batchHistory: [...prior, batch],
        activeBatchId: batch.request_id,
        isCompletedBatchesRestored: true,
        shouldRedirectToResults: disposition.shouldRedirectToResults,
        error: null,
      })
      return 'restored'
    } catch (error) {
      if (get().requestId !== active.requestId) return 'stale'
      if (
        phase === 'restore'
        && error instanceof GenerationApiError
        && error.code === 'generation_not_found'
      ) {
        clearActiveGeneration()
        set({
          domainLabel: '',
          domainSuffix: '.com',
          error: null,
          requestId: null,
          isProcessing: false,
          isRegenerating: false,
          completedGeneration: null,
          batchHistory: [],
          activeBatchId: null,
          isCompletedBatchesRestored: true,
          shouldRedirectToResults: false,
        })
        return 'stale'
      }
      set({
        isProcessing: false,
        isRegenerating: false,
        isCompletedBatchesRestored: true,
        error: error instanceof GenerationApiError ? error.message : '生成状态查询失败，请稍后重试。',
      })
      return 'restored'
    }
  }

  const begin = async (
    domainLabel: string,
    domainSuffix: DomainSuffix,
    phase: 'creation' | 'regeneration',
    allowInvalidSourceFallback = true,
  ): Promise<void> => {
    recoverySequence += 1
    const sourceImageAssetId = get().sourceImageAssetId
    const userReferenceRequirement = get().userReferenceRequirement.trim()
    let accepted
    try {
      accepted = await createBatchGeneration(
        domainLabel,
        domainSuffix,
        sourceImageAssetId,
        sourceImageAssetId ? userReferenceRequirement : null,
      )
    } catch (error) {
      if (
        allowInvalidSourceFallback
        && error instanceof GenerationApiError
        && error.code === 'invalid_source_image'
        && sourceImageAssetId
      ) {
        get().clearSourceImage()
        await begin(domainLabel, domainSuffix, phase, false)
        return
      }
      throw error
    }
    if (accepted === 'completed_task_exists') {
      set({ isProcessing: false, isRegenerating: false })
      useToastStore.getState().showToast('已有完成的任务，请前往我的方案查看')
      return
    }
    const active: ActiveGeneration = {
      requestId: accepted.request_id,
      ...(isMockMode ? {
        domain: `${domainLabel}${domainSuffix}`,
        domainLabel,
        domainSuffix,
        submittedAt: Date.now(),
        targetCount: accepted.target_count,
      } : {}),
    }
    writeActiveGeneration(active)
    set({
      requestId: accepted.request_id,
      isProcessing: phase === 'creation',
      isRegenerating: phase === 'regeneration',
      completedGeneration: phase === 'creation' ? null : get().completedGeneration,
      activeBatchId: phase === 'creation' ? null : get().activeBatchId,
      isCompletedBatchesRestored: phase !== 'creation',
      shouldRedirectToResults: false,
      error: null,
    })
    void poll(active, phase)
  }

  return {
    domainLabel: initialActiveGeneration?.domainLabel ?? '',
    domainSuffix: initialActiveGeneration?.domainSuffix ?? '.com',
    sourceImageAssetId: null,
    userReferenceRequirement: '',
    error: null,
    requestId: initialActiveGeneration?.requestId ?? null,
    isProcessing: initialActiveGeneration !== null,
    isRegenerating: false,
    completedGeneration: null,
    batchHistory: [],
    activeBatchId: null,
    isCompletedBatchesRestored: false,
    shouldRedirectToResults: false,
    setDomainLabel: (domainLabel) => set({ domainLabel, error: null }),
    retryingSlots: [],
    setDomainSuffix: (domainSuffix) => set({ domainSuffix, error: null }),
    setSourceImageAssetId: (sourceImageAssetId) => set({ sourceImageAssetId, error: null }),
    setUserReferenceRequirement: (userReferenceRequirement) => set({ userReferenceRequirement, error: null }),
    clearSourceImage: () => {
      clearGenerationSourceRecovery()
      set({ sourceImageAssetId: null, userReferenceRequirement: '', error: null })
    },
    generate: async () => {
      if (get().isProcessing) return
      const domainLabel = get().domainLabel.trim()
      const domainSuffix = get().domainSuffix
      if (!domainLabel) {
        set({ error: '请先输入需要设计 Logo 的域名。' })
        return
      }
      set({ domainLabel })
      set({ isProcessing: true, error: null })
      try {
        await begin(domainLabel, domainSuffix, 'creation')
      } catch (error) {
        set({
          isProcessing: false,
          error: error instanceof GenerationApiError ? error.message : '批量生成请求失败，请稍后重试。',
        })
      }
    },
    regenerate: async () => {
      const current = get().completedGeneration
      if (!current || get().isRegenerating || !regenerationGate.tryEnter()) return
      set({ isRegenerating: true, error: null })
      try {
        await begin(current.domainLabel, current.domainSuffix, 'regeneration')
      } catch (error) {
        set({
          isRegenerating: false,
          error: error instanceof GenerationApiError ? error.message : '新一批方案生成失败，请稍后重试。',
        })
      } finally {
        regenerationGate.leave()
      }
    },
    retrySlot: async (requestId, slotIndex, retryToken) => {
      const slotKey = `${requestId}:${slotIndex}`
      if (get().retryingSlots.includes(slotKey)) return
      const initialBatch = get().batchHistory.find((batch) => batch.request_id === requestId)
      const initialFailureSignature = candidateFailureSignature(initialBatch, slotIndex)
      set({ retryingSlots: [...get().retryingSlots, slotKey], error: null })
      try {
        const idempotencyKey = crypto.randomUUID()
        await retryBatchGenerationSlot(requestId, slotIndex, retryToken, idempotencyKey)
        let sawRetryInProgress = false
        let terminal = false
        for (let pollCount = 0; pollCount < slotRetryMaxPolls; pollCount += 1) {
          const response = await getBatchGenerationStatus(requestId, null)
          if (!isRealStatus(response)) {
            throw new Error('方案重试状态响应无效。')
          }
          const batchWindow = resolveSuccessfulBatchWindow(
            response.batches, get().activeBatchId, requestId,
          )
          const mergedBatches = mergeRetriedBatchWindow(
            get().batchHistory,
            batchWindow.batches,
            requestId,
            slotIndex,
          )
          const latestBatch = batchWindow.latestBatch
            ? mergedBatches.find((batch) => batch.request_id === batchWindow.latestBatch?.request_id)
            : undefined
          set({
            batchHistory: mergedBatches,
            activeBatchId: batchWindow.activeBatchId,
            completedGeneration: batchCompletion(latestBatch),
          })
          const slot = response.batches
            .find((batch) => batch.request_id === requestId)
            ?.candidates.find((candidate) => candidate.slot_index === slotIndex)
          if (!slot) throw new Error('方案重试状态响应缺少目标槽位。')
          if (slot?.status === 'succeeded') {
            terminal = true
            break
          }
          if (slot?.failure?.code === 'retry_in_progress' || !slot?.retry_token) {
            sawRetryInProgress = true
          } else {
            const failureSignature = `${slot.failure?.code ?? ''}:${slot.failure?.message ?? ''}`
            const hasFreshFailure = slot.retry_token !== retryToken
              || failureSignature !== initialFailureSignature
              || sawRetryInProgress
            if (hasFreshFailure) {
              terminal = true
              break
            }
          }
          await waitForSlotRetryPoll()
        }
        if (!terminal) throw new Error('方案重试等待超时，请稍后再试。')
      } catch (error) {
        set({
          error: error instanceof GenerationApiError
            ? error.message
            : error instanceof Error && error.message
              ? error.message
              : '方案重试失败，请稍后再试。',
        })
      } finally {
        set({
          retryingSlots: get().retryingSlots.filter((key) => key !== slotKey),
        })
      }
    },
    selectBatch: (requestId) => {
      if (!get().batchHistory.some((batch) => batch.request_id === requestId)) return
      set({ activeBatchId: requestId })
    },
    restoreActiveGeneration: async () => {
      const recoveryId = ++recoverySequence
      try {
        await recoverInitialGeneration({
          readActive: readActiveGeneration,
          restoreActive: async (active) => {
            if (recoveryId !== recoverySequence) return 'stale'
            set({ requestId: active.requestId, isProcessing: true, error: null })
            return poll(active, 'restore')
          },
          onNoActive: () => {
            if (recoveryId !== recoverySequence) return
            set({
              domainLabel: '',
              domainSuffix: '.com',
              error: null,
              requestId: null,
              isProcessing: false,
              isRegenerating: false,
              completedGeneration: null,
              batchHistory: [],
              activeBatchId: null,
              isCompletedBatchesRestored: false,
              shouldRedirectToResults: false,
            })
          },
          fetchLatest: async () => (await getLatestSuccessfulGeneration()).latest,
          isCurrent: () => recoveryId === recoverySequence
            && get().requestId === null
            && !get().isProcessing,
          applyLatest: (latest) => {
            const batchWindow = resolveSuccessfulBatchWindow(
              latest?.batches ?? [],
              null,
              latest?.request_id ?? null,
            )
            set({
              completedGeneration: batchCompletion(batchWindow.latestBatch ?? undefined),
              batchHistory: batchWindow.batches,
              activeBatchId: batchWindow.activeBatchId,
              isCompletedBatchesRestored: true,
              shouldRedirectToResults: false,
              error: null,
            })
          },
        })
      } catch (error) {
        if (recoveryId !== recoverySequence) return
        set({
          isCompletedBatchesRestored: true,
          error: error instanceof GenerationApiError ? error.message : null,
        })
      }
    },
    restoreCompletedBatches: async () => {
      if (get().batchHistory.length > 0) {
        set({ isCompletedBatchesRestored: true })
        return
      }
      await get().restoreActiveGeneration()
    },
    returnToCreation: () => {
      clearActiveGeneration()
      clearGenerationSourceRecovery()
      set({
        domainLabel: '',
        domainSuffix: '.com',
        sourceImageAssetId: null,
        userReferenceRequirement: '',
        error: null,
        requestId: null,
        isProcessing: false,
        shouldRedirectToResults: false,
      })
    },
    clearCustomerState: () => {
      recoverySequence += 1
      clearActiveGeneration()
      clearGenerationSourceRecovery()
      set({
        domainLabel: '',
        domainSuffix: '.com',
        sourceImageAssetId: null,
        userReferenceRequirement: '',
        error: null,
        requestId: null,
        isProcessing: false,
        isRegenerating: false,
        completedGeneration: null,
        batchHistory: [],
        activeBatchId: null,
        isCompletedBatchesRestored: false,
        shouldRedirectToResults: false,
      })
    },
  }
})
