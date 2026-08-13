import { spawnSync } from 'node:child_process'

const isWindows = process.platform === 'win32'
const npmCommand = isWindows ? 'npm.cmd' : 'npm'
const build = spawnSync(npmCommand, ['run', 'build'], {
  env: { ...process.env, VITE_USE_MOCK: 'false' },
  shell: isWindows,
  stdio: 'inherit',
})

if (build.error) throw build.error
if (build.status !== 0) process.exit(build.status ?? 1)

const assertion = spawnSync(process.execPath, ['scripts/assert-real-build.mjs'], {
  stdio: 'inherit',
})

if (assertion.error) throw assertion.error
process.exit(assertion.status ?? 1)
