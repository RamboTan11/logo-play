interface InitialGenerationRecoveryOptions<TActive, TLatest> {
  readActive: () => TActive | null
  restoreActive: (active: TActive) => Promise<'restored' | 'stale'>
  onNoActive: () => void
  fetchLatest: () => Promise<TLatest | null>
  isCurrent: () => boolean
  applyLatest: (latest: TLatest | null) => void
}

type GenerationPollPhase = 'creation' | 'regeneration' | 'restore'
type GenerationPollStatus = 'processing' | 'succeeded' | 'failed'

interface GenerationPollDisposition {
  clearActiveRequest: boolean
  restoreLatestSuccessful: boolean
  shouldRedirectToResults: boolean
}

export function resolveGenerationPollDisposition(
  status: GenerationPollStatus,
  phase: GenerationPollPhase,
): GenerationPollDisposition {
  const isTerminal = status !== 'processing'
  return {
    clearActiveRequest: isTerminal,
    restoreLatestSuccessful: isTerminal && phase === 'restore',
    shouldRedirectToResults: status === 'succeeded' && phase !== 'restore',
  }
}

export async function recoverInitialGeneration<TActive, TLatest>(
  options: InitialGenerationRecoveryOptions<TActive, TLatest>,
): Promise<'active' | 'latest' | 'empty' | 'stale'> {
  const active = options.readActive()
  if (active && await options.restoreActive(active) === 'restored') return 'active'

  options.onNoActive()
  const latest = await options.fetchLatest()
  if (!options.isCurrent()) return 'stale'
  options.applyLatest(latest)
  return latest === null ? 'empty' : 'latest'
}
