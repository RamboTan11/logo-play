import { resolve } from 'node:path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function requestedPort(): number {
  const equalsPort = process.argv.find((argument) => argument.startsWith('--port='))
  if (equalsPort) return Number(equalsPort.split('=', 2)[1])
  const portIndex = process.argv.findIndex((argument) => argument === '--port')
  return portIndex >= 0 ? Number(process.argv[portIndex + 1]) : 5199
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const mockMode = process.env.VITE_USE_MOCK ?? env.VITE_USE_MOCK ?? 'true'
  const backendTarget = process.env.VITE_BACKEND_PROXY_TARGET
    ?? env.VITE_BACKEND_PROXY_TARGET
    ?? 'http://localhost:8099'
  const publicBasePath = process.env.VITE_PUBLIC_BASE_PATH
    ?? env.VITE_PUBLIC_BASE_PATH
    ?? '/'
  const serverPort = requestedPort()
  const useMock = mockMode === 'true'

  return {
    plugins: [react()],
    base: publicBasePath.endsWith('/') ? publicBasePath : `${publicBasePath}/`,
    define: {
      'import.meta.env.VITE_USE_MOCK': JSON.stringify(mockMode),
    },
    resolve: {
      alias: {
        '@model-strategy-runtime': resolve(
          process.cwd(),
          useMock ? 'src/mocks/modelStrategyMock.ts' : 'src/services/modelStrategyUnavailable.ts',
        ),
      },
    },
    server: {
      port: serverPort,
      proxy: {
        '/api': { target: backendTarget, changeOrigin: true },
        '/ws': { target: backendTarget.replace(/^http/, 'ws'), changeOrigin: true, ws: true },
      },
    },
  }
})
