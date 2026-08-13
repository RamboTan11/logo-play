import type { ApiResponse, VerifyAccessData, VerifyAccessRequest } from '../types/api'

const accessLinks: Record<string, number> = {
  'mock-valid': 0,
  'mock-expired': 401,
  'mock-suspended': 403,
}

export async function verifyAccessMock(
  request: VerifyAccessRequest,
): Promise<ApiResponse<VerifyAccessData>> {
  await new Promise((resolve) => window.setTimeout(resolve, 180))
  const code = accessLinks[request.token] ?? 401

  return code === 0
      ? { code: 0, message: '授权有效', data: {} }
      : code === 403
        ? { code: 403, message: '访问已暂停', data: {} }
        : { code: 401, message: '访问链接已过期', data: {} }
}
