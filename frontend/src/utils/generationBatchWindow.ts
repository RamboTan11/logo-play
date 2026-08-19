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
  // The API owns retention. Keep the active processing batch alongside history so
  // its already-completed candidate slots can appear before the request finishes.
  const visibleBatches = batches.filter((batch) => batch.status !== 'failed')
  const latestBatch = visibleBatches.at(-1) ?? null
  const committedBatch = committedRequestId
    ? visibleBatches.find((batch) => batch.request_id === committedRequestId)
    : null
  const activeBatchId = committedBatch?.request_id
    ?? (currentActiveBatchId && visibleBatches.some((batch) => batch.request_id === currentActiveBatchId)
      ? currentActiveBatchId
      : latestBatch?.request_id ?? null)

  return { batches: visibleBatches, activeBatchId, latestBatch }
}

export function mergeGenerationBatchWindow(
  currentBatches: GenerationBatch[],
  incomingBatches: GenerationBatch[],
): GenerationBatch[] {
  const incomingById = new Map(incomingBatches.map((batch) => [batch.request_id, batch]))
  const merged = currentBatches.map((batch) => incomingById.get(batch.request_id) ?? batch)
  for (const batch of incomingBatches) {
    if (!currentBatches.some((current) => current.request_id === batch.request_id)) merged.push(batch)
  }
  return merged.sort((left, right) => left.created_at.localeCompare(right.created_at))
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
