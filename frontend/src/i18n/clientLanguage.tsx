import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'

export type ClientLanguage = 'zh-CN' | 'en'

const storageKey = 'logo-generated.client-language'

const english: Record<string, string> = {
  'Logo素材生成': 'Logo Studio',
  '客户侧导航': 'Customer navigation',
  '创作': 'Create',
  '我的方案': 'My Designs',
  '访问链接无效': 'Invalid access link',
  '请确认你打开的是当前有效的访问链接。': 'Please confirm that you opened the current valid access link.',
  '访问尚未启用': 'Access has not started',
  '当前访问权限尚未开始，请联系项目负责人。': 'This access permission has not started. Please contact the project owner.',
  '访问已关停': 'Access has been stopped',
  '当前访问权限已关停，请联系项目负责人。': 'This access permission has been stopped. Please contact the project owner.',
  '访问链接已到期': 'Access link expired',
  '本次访问权限已结束，请联系项目负责人。': 'This access permission has ended. Please contact the project owner.',
  '暂时无法验证': 'Unable to verify access',
  '服务暂时不可用，请稍后重新打开访问链接。': 'The service is temporarily unavailable. Please reopen the access link later.',
  '正在验证访问': 'Verifying access',
  '正在确认你的访问权限，请稍候。': 'We are confirming your access permission. Please wait.',
  'Logo 创作': 'Logo creation',
  '查看生成结果': 'View generated results',
  '正在生成 Logo 方案': 'Generating logo concepts',
  '正在根据你的域名探索设计方向，生成结果会自动显示': 'Exploring design directions for your domain. Results will appear automatically.',
  '品牌域名': 'Brand domain',
  '请输入域名前缀，如 igame': 'Enter a domain prefix, for example igame',
  '域名后缀': 'Domain suffix',
  '选择域名后缀': 'Choose a domain suffix',
  '正在上传视觉参考': 'Uploading visual reference',
  '上传视觉参考': 'Upload visual reference',
  '上传视觉参考（选填）': 'Upload visual reference (optional)',
  '视觉参考': 'Visual reference',
  '选填': 'Optional',
  '上传中': 'Uploading',
  '删除视觉参考': 'Remove visual reference',
  '参考要求（选填）': 'Reference instructions (optional)',
  '请输入图片参考要求，默认保留其中辨识度的主体图形、结构关系、独特视觉特征（可留空）。': 'Describe what to retain from the image, such as its distinctive subject, structural relationships, and unique visual features. You may leave this blank.',
  '生成创意初稿': 'Generate concepts',
  '本次将生成平面创意初稿，采用后由我们继续优化为最终成品。': 'This creates initial flat concepts. After you adopt one, we will continue refining it into the final deliverable.',
  '仅支持 PNG、JPEG 或 WebP 图片。': 'Only PNG, JPEG, or WebP images are supported.',
  '视觉参考图片不能超过 10 MB。': 'Visual reference images must not exceed 10 MB.',
  '正在恢复生成结果...': 'Restoring generated results...',
  '暂无可查看的生成结果。': 'There are no generated results to view.',
  '返回创作': 'Back to creation',
  '收藏成功，可前往': 'Saved successfully. Go to',
  '查看': 'view',
  '收藏失败。': 'Unable to save.',
  '提交成功': 'Submitted successfully',
  '采用成功，可前往': 'Adopted successfully. Go to',
  '采用失败。': 'Unable to adopt.',
  '生成结果': 'Generated results',
  '生成批次工具': 'Generation batch tools',
  '上一批': 'Previous batch',
  '下一批': 'Next batch',
  '换一批': 'Generate another batch',
  '本批方案未能完整生成': 'This batch could not be generated completely',
  '请稍后重新生成。': 'Please generate another batch later.',
  'Logo 方案列表': 'Logo concept list',
  '重试失败方案': 'Retry failed concept',
  '重试此方案': 'Retry this concept',
  '此方案生成失败，请重试。': 'This concept could not be generated. Please retry.',
  '正在重试...': 'Retrying...',
  '选择方案': 'Select concept',
  '单图编辑': 'Edit concept',
  '生成的 Logo': 'Generated logo',
  '正在生成新一批方案': 'Generating another batch',
  '正在探索新的设计方向，生成结果会自动显示': 'Exploring new design directions. Results will appear automatically.',
  '选择初稿': 'Select a concept',
  '采用后由我们继续优化为最终成品': 'After adoption, we will continue refining it into the final deliverable.',
  '优化要求（选填）': 'Refinement instructions (optional)',
  '可输入优化要求，默认优化为行业品牌特色的立体效果。': 'Add refinement instructions. By default, we refine the design into a dimensional look suited to the brand category.',
  '收藏中...': 'Saving...',
  '收藏': 'Save',
  '采用初稿': 'Adopt concept',
  '采用': 'Adopt',
  '采用后将进入成品优化，并由我们完成最终交付': 'After adoption, the concept enters final refinement and we complete the delivery.',
  '确认变更方案': 'Confirm design change',
  '确认采用方案': 'Confirm adoption',
  '关闭采用确认': 'Close adoption confirmation',
  '已有提交的方案，请确认是否发起变更': 'A design has already been submitted. Confirm whether to start a change.',
  '人工精修建议（选填）': 'Manual refinement notes (optional)',
  '可输入你的精修建议': 'Enter your refinement notes',
  '取消': 'Cancel',
  '提交中...': 'Submitting...',
  '确认变更': 'Confirm change',
  '确认采用': 'Confirm adoption',
  '预计需 1～3 分钟，请稍等': 'This usually takes 1-3 minutes. Please wait.',
  '正在加载当前版本...': 'Loading the current version...',
  '返回生成结果': 'Back to generated results',
  '单图编辑工具': 'Single-concept editing tools',
  '上一版本': 'Previous version',
  '下一版本': 'Next version',
  '生成修改版本': 'Generate edited version',
  '只修改指令中明确点名的部分。': 'Only the parts explicitly named in the instruction will be changed.',
  '修改指令': 'Edit instruction',
  '例如：仅将图标改为金色，文字、构图和其他颜色保持不变': 'For example: change only the icon to gold; keep the text, composition, and other colors unchanged.',
  '修改版本生成中': 'Generating edited version',
  '当前版本': 'Current version',
  '完成后自动呈现': 'Will appear automatically when complete',
  '初始生成': 'Initial generation',
  '当前 Logo 版本': 'Current logo version',
  '当前版本已安全保留': 'The current version is safely preserved',
  '生成完成后会自动切换到新版本': 'The view will switch to the new version when generation is complete',
  '保持当前方向': 'Keep the current direction',
  '仅显示当前版本与紧邻上一版本': 'Showing the current version and its immediately previous version only',
  '当前版本操作': 'Current version actions',
  '已生成新版本': 'A new version has been generated',
  '新版本生成失败，请稍后重试。': 'The new version could not be generated. Please retry later.',
  '新版本状态查询失败。': 'Unable to check the new version status.',
  '单图编辑内容加载失败。': 'Unable to load the single-concept editor.',
  '请填写修改指令。': 'Please enter an edit instruction.',
  '生成新版本失败，请稍后重试。': 'Unable to generate a new version. Please retry later.',
  '正在加载方案与任务...': 'Loading designs and tasks...',
  '重试': 'Retry',
  '收藏方案': 'Saved designs',
  '收藏方案横向列表': 'Horizontal saved designs list',
  '暂无收藏方案': 'No saved designs yet',
  '方案列表': 'Design list',
  '暂无任务': 'No tasks yet',
  '域名': 'Domain',
  '采用图片': 'Adopted image',
  '精修建议': 'Refinement notes',
  '提交时间': 'Submitted',
  '状态': 'Status',
  '精修图片': 'Refined image',
  '上传时间': 'Uploaded',
  '操作': 'Actions',
  '待接单': 'Awaiting assignment',
  '待上传': 'Awaiting upload',
  '已完成': 'Completed',
  '已取消': 'Canceled',
  '已收藏方案': 'Saved design',
  '编辑': 'Edit',
  '已有完成交付的方案，无法再次提交。若需变更方案，请联系运营人员处理。': 'A completed delivery cannot be submitted again. Contact operations if you need to change the design.',
  '已有完成交付的方案，请前往': 'A completed design has already been delivered. Go to',
  '预览': 'Preview',
  '加载中...': 'Loading...',
  '查看详情': 'View details',
  '修改建议': 'Edit notes',
  '方案详情': 'Design details',
  '关闭方案详情': 'Close design details',
  '精修图片未上传': 'Refined image not uploaded',
  '关闭图片预览': 'Close image preview',
  '采用成功': 'Adopted successfully',
  '修改建议已提交': 'Refinement notes submitted',
  '方案与任务加载失败，请稍后重试。': 'Unable to load designs and tasks. Please retry later.',
  '方案详情加载失败，请稍后重试。': 'Unable to load design details. Please retry later.',
  '修改建议失败，请稍后重试。': 'Unable to update refinement notes. Please retry later.',
  '正在加载任务...': 'Loading task...',
  '返回我的方案': 'Back to my designs',
  '未找到该任务': 'Task not found',
  '精修终稿': 'Final refined image',
  '精修终稿待交付': 'Final refined image pending delivery',
  '待交付': 'Pending delivery',
  '人工精修建议': 'Manual refinement notes',
}

interface ClientLanguageContextValue {
  language: ClientLanguage
  setLanguage: (language: ClientLanguage) => void
  t: (source: string) => string
}

const ClientLanguageContext = createContext<ClientLanguageContextValue | null>(null)

function initialLanguage(): ClientLanguage {
  if (typeof window === 'undefined') return 'zh-CN'
  return window.localStorage.getItem(storageKey) === 'en' ? 'en' : 'zh-CN'
}

export function ClientLanguageProvider({ children }: PropsWithChildren) {
  const [language, setLanguageState] = useState<ClientLanguage>(initialLanguage)
  const setLanguage = (nextLanguage: ClientLanguage) => {
    setLanguageState(nextLanguage)
    window.localStorage.setItem(storageKey, nextLanguage)
  }

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const value = useMemo(() => ({
    language,
    setLanguage,
    t: (source: string) => language === 'en' ? english[source] ?? source : source,
  }), [language])

  return <ClientLanguageContext.Provider value={value}>{children}</ClientLanguageContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useClientLanguageContext(): ClientLanguageContextValue {
  const context = useContext(ClientLanguageContext)
  if (!context) throw new Error('useClientLanguage must be used within ClientLanguageProvider')
  return context
}
