import type { GenerationBatch } from '../types/api'

interface SuccessfulBatchWindow {
  batches: GenerationBatch[]
  activeBatchId: string | null
  latestBatch: GenerationBatch | null
}

export function resolveSuccessfulBatchWindow(
  batches: GenerationBatch[],
  currentActiveBatchId: string | null,
  committedRequestId: string | null = null,
): SuccessfulBatchWindow {
  // The API owns retention. Keep every successful batch returned for this customer.
  const successfulBatches = batches.filter((batch) => batch.status === 'succeeded')
  const latestBatch = successfulBatches.at(-1) ?? null
  const committedBatch = committedRequestId
    ? successfulBatches.find((batch) => batch.request_id === committedRequestId)
    : null
  const activeBatchId = committedBatch?.request_id
    ?? (currentActiveBatchId && successfulBatches.some((batch) => batch.request_id === currentActiveBatchId)
      ? currentActiveBatchId
      : latestBatch?.request_id ?? null)

  return { batches: successfulBatches, activeBatchId, latestBatch }
}

export function mergeRetriedBatchWindow(
  currentBatches: GenerationBatch[],
  incomingBatches: GenerationBatch[],
  requestId: string,
  slotIndex: number,
): GenerationBatch[] {
  return incomingBatches.map((incomingBatch) => {
    const currentBatch = currentBatches.find(
      (batch) => batch.request_id === incomingBatch.request_id,
    )
    if (!currentBatch) return incomingBatch
    if (incomingBatch.request_id !== requestId) return currentBatch

    const currentCandidates = new Map(
      currentBatch.candidates.map((candidate) => [candidate.slot_index, candidate]),
    )
    return {
      ...incomingBatch,
      candidates: incomingBatch.candidates.map((candidate) => (
        candidate.slot_index === slotIndex
          ? candidate
          : currentCandidates.get(candidate.slot_index) ?? candidate
      )),
    }
  })
}
