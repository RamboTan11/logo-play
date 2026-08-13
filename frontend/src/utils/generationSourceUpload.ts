import type { GenerationSourceAsset } from '../types/api'

export interface GenerationSourceUploadState {
  assetId: string | null
  filename: string | null
  previewUrl: string | null
  isUploading: boolean
}

export const initialGenerationSourceUploadState: GenerationSourceUploadState = {
  assetId: null,
  filename: null,
  previewUrl: null,
  isUploading: false,
}

interface GenerationSourceUploadLifecycleOptions {
  createObjectUrl: (content: Blob) => string
  revokeObjectUrl: (url: string) => void
  onError: (message: string) => void
  onStateChange: (state: GenerationSourceUploadState) => void
  upload: (file: File, signal: AbortSignal) => Promise<GenerationSourceAsset>
}

export class GenerationSourceUploadLifecycle {
  private activeController: AbortController | null = null
  private state = initialGenerationSourceUploadState
  private readonly options: GenerationSourceUploadLifecycleOptions

  constructor(options: GenerationSourceUploadLifecycleOptions) {
    this.options = options
  }

  getState(): GenerationSourceUploadState {
    return this.state
  }

  canGenerate(): boolean {
    return !this.state.isUploading
  }

  async choose(file: File): Promise<void> {
    if (this.state.isUploading) return

    const controller = new AbortController()
    this.activeController = controller
    this.replacePreview(this.options.createObjectUrl(file))
    this.publish({
      assetId: null,
      filename: file.name,
      isUploading: true,
      previewUrl: this.state.previewUrl,
    })

    try {
      const asset = await this.options.upload(file, controller.signal)
      if (controller.signal.aborted || this.activeController !== controller) return
      this.publish({
        assetId: asset.id,
        filename: asset.filename,
        isUploading: false,
        previewUrl: this.state.previewUrl,
      })
    } catch (error) {
      if (controller.signal.aborted || this.activeController !== controller) return
      this.replacePreview(null)
      this.publish({ ...initialGenerationSourceUploadState })
      this.options.onError(error instanceof Error ? error.message : '视觉参考上传失败，请稍后重试。')
    } finally {
      if (this.activeController === controller) this.activeController = null
    }
  }

  restore(assetId: string, filename: string, content: Blob): void {
    if (this.state.isUploading) return
    this.replacePreview(this.options.createObjectUrl(content))
    this.publish({ assetId, filename, previewUrl: this.state.previewUrl, isUploading: false })
  }

  remove(): void {
    if (this.state.isUploading) return
    this.replacePreview(null)
    this.publish({ ...initialGenerationSourceUploadState })
  }

  clear(): void {
    this.activeController?.abort()
    this.activeController = null
    this.replacePreview(null)
    this.publish({ ...initialGenerationSourceUploadState })
  }

  dispose(): void {
    this.activeController?.abort()
    this.activeController = null
    this.replacePreview(null)
    this.state = { ...initialGenerationSourceUploadState }
  }

  private replacePreview(nextUrl: string | null): void {
    if (this.state.previewUrl) this.options.revokeObjectUrl(this.state.previewUrl)
    this.state = { ...this.state, previewUrl: nextUrl }
  }

  private publish(state: GenerationSourceUploadState): void {
    this.state = state
    this.options.onStateChange(state)
  }
}
