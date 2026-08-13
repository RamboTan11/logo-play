import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'

const forbiddenFragments = [
  'mock-secret-not-returned',
  'seedream-4.0-mock-primary',
  'mock-model-001',
  'mock-batch-policy-v1',
]

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? filesUnder(path) : [path]
  }))
  return nested.flat()
}

const artifacts = await filesUnder(join(process.cwd(), 'dist'))
const contents = await Promise.all(artifacts.map((path) => readFile(path, 'utf8')))
const leaks = forbiddenFragments.filter((fragment) => contents.some((content) => content.includes(fragment)))

if (leaks.length > 0) {
  throw new Error(`Real build contains Mock model strategy data: ${leaks.join(', ')}`)
}

const viteConfig = await readFile(join(process.cwd(), 'vite.config.ts'), 'utf8')
const productSource = await Promise.all([
  readFile(join(process.cwd(), 'src/pages/AdminLoginPage.tsx'), 'utf8'),
  readFile(join(process.cwd(), 'src/pages/CustomerAccessPage.tsx'), 'utf8'),
])

for (const developmentToken of ['local-dev-admin', 'local-dev-customer-link']) {
  if (viteConfig.includes(developmentToken)) {
    throw new Error('Real browser proxy must not inject development authentication')
  }
}
if (productSource.some((source) => source.includes('占位'))) {
  throw new Error('Empty error regions must not expose placeholder alerts')
}
if (!productSource[1].includes('<GlobalToast />')) {
  throw new Error('Customer access operations require the global Toast renderer')
}
