export const generationSourceRecoveryStorageKey = 'logo-generated.generation-source-recovery'

export interface GenerationSourceRecoveryMetadata {
  assetId: string
  filename: string
  requirement: string
}

function browserStorage(): Storage | null {
  return typeof window === 'undefined' ? null : window.localStorage
}

export function readGenerationSourceRecovery(
  storage: Storage | null = browserStorage(),
): GenerationSourceRecoveryMetadata | null {
  if (!storage) return null
  try {
    const parsed: unknown = JSON.parse(storage.getItem(generationSourceRecoveryStorageKey) ?? 'null')
    if (
      typeof parsed !== 'object'
      || parsed === null
      || !('asset_id' in parsed)
      || !('filename' in parsed)
      || !('requirement' in parsed)
      || typeof parsed.asset_id !== 'string'
      || !parsed.asset_id
      || typeof parsed.filename !== 'string'
      || !parsed.filename
      || typeof parsed.requirement !== 'string'
    ) {
      storage.removeItem(generationSourceRecoveryStorageKey)
      return null
    }
    return {
      assetId: parsed.asset_id,
      filename: parsed.filename,
      requirement: parsed.requirement,
    }
  } catch {
    storage.removeItem(generationSourceRecoveryStorageKey)
    return null
  }
}

export function writeGenerationSourceRecovery(
  metadata: GenerationSourceRecoveryMetadata,
  storage: Storage | null = browserStorage(),
): void {
  if (!storage) return
  storage.setItem(generationSourceRecoveryStorageKey, JSON.stringify({
    asset_id: metadata.assetId,
    filename: metadata.filename,
    requirement: metadata.requirement,
  }))
}

export function clearGenerationSourceRecovery(
  storage: Storage | null = browserStorage(),
): void {
  storage?.removeItem(generationSourceRecoveryStorageKey)
}
