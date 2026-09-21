/**
 * Live end-to-end fixture: a real worktree-review-server process with a fresh
 * SQLite database, a real lightweight git repository, a real local-cli review
 * command (no shell, no network), trusted policy files, and a stub Session
 * Insight deployment. Nothing is mocked at the HTTP layer.
 */
import { execFileSync, spawn, type ChildProcess } from 'node:child_process'
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as os from 'node:os'
import * as path from 'node:path'

import { fileURLToPath } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

export interface LiveFixture {
  baseUrl: string
  workDir: string
  repositoryDir: string
  controlPath: string
  reviewPolicyPath: string
  userConfigPath: string
  journalRoot: string
  sessionInsightUrl: string
  pythonExecutable: string
  reviewerArgv: string[]
  cleanup: () => Promise<void>
}

export function setControlMode(controlPath: string, mode: 'pass' | 'block' | 'fail'): void {
  const finding = {
    path: 'README.md',
    start_line: 1,
    end_line: 1,
    quoted_text: 'hello live fixture',
    severity: 'major',
    evidence_band: 'verified',
    problem_statement: 'README contains a placeholder line that must not ship.',
    expected_impact: 'Placeholder content reaches production.',
    repair_guidance: 'Replace the placeholder with real content.',
  }
  fs.writeFileSync(
    controlPath,
    JSON.stringify({ mode, finding: mode === 'block' ? finding : null }),
    'utf-8',
  )
}

const REVIEWER_SCRIPT = `import json, sys
control = json.load(open(sys.argv[1], encoding="utf-8"))
request = json.load(sys.stdin)
mode = control.get("mode", "pass")
if mode == "fail":
    print("fixture reviewer exploded", file=sys.stderr)
    sys.exit(2)
finding = control.get("finding")
json.dump({"findings": [finding] if finding else []}, sys.stdout)
`

const REVIEW_POLICY_YAML = `\
schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
blocking_severities:
  - critical
  - major
minimum_blocking_evidence_band: supported
`

function userConfigYaml(argv: string[]): string {
  const command = argv.map((argument) => JSON.stringify(argument)).join(', ')
  return `\
schema: worktree-review.config/v1
version: 0.1.0
provider: local-cli
command: [${command}]
model: fixture-reviewer
`
}

async function waitForHealthz(baseUrl: string, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const response = await fetch(`${baseUrl}/healthz`)
      if (response.ok) {
        return
      }
    } catch {
      // not up yet
    }
    if (Date.now() > deadline) {
      throw new Error(`server did not become healthy at ${baseUrl}`)
    }
    await new Promise((resolve) => setTimeout(resolve, 250))
  }
}

function resolveLiveScratchBase(): string {
  // Prefer ~/tmp (project convention). Fall back to TMPDIR /
  // WORKTREE_REVIEW_TEST_TMP when the home scratch tree is not writable
  // (for example a workspace sandbox), but only under known throwaway roots.
  const homeTmp = path.join(os.homedir(), 'tmp')
  const candidates = [
    homeTmp,
    process.env.WORKTREE_REVIEW_TEST_TMP,
    process.env.TMPDIR,
  ].filter((value): value is string => typeof value === 'string' && value.length > 0)
  const allowedRoots = new Set([homeTmp, '/var/tmp', path.join(homeTmp, 'worktree-review')])
  const errors: string[] = []
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate)
    const allowed = [...allowedRoots].some(
      (root) => resolved === path.resolve(root) || resolved.startsWith(`${path.resolve(root)}${path.sep}`),
    )
    if (!allowed && resolved !== path.resolve(homeTmp)) {
      continue
    }
    try {
      fs.mkdirSync(resolved, { recursive: true })
      const probe = path.join(resolved, `.wr-live-probe-${process.pid}`)
      fs.writeFileSync(probe, 'ok')
      fs.unlinkSync(probe)
      return resolved
    } catch (error) {
      errors.push(`${resolved}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  throw new Error(
    `no writable live-e2e scratch root under ~/tmp or an allowed TMPDIR; tried: ${errors.join('; ')}`,
  )
}

export async function startLiveFixture(): Promise<LiveFixture> {
  const scratchBase = resolveLiveScratchBase()
  const workDir = fs.mkdtempSync(path.join(scratchBase, 'wr-live-e2e-'))
  const repositoryDir = path.join(workDir, 'repo')
  fs.mkdirSync(repositoryDir)
  const git = (args: string[]) =>
    execFileSync('git', args, { cwd: repositoryDir, stdio: 'pipe' })
  git(['init', '-b', 'main'])
  git(['config', 'user.email', 'live-e2e@example.com'])
  git(['config', 'user.name', 'Live E2E'])
  fs.writeFileSync(path.join(repositoryDir, 'README.md'), 'hello live fixture\n')
  git(['add', 'README.md'])
  git(['commit', '-m', 'initial'])

  const trustedDir = path.join(workDir, 'trusted')
  fs.mkdirSync(trustedDir)
  const reviewPolicyPath = path.join(trustedDir, 'review-policy.yaml')
  fs.writeFileSync(reviewPolicyPath, REVIEW_POLICY_YAML)

  const reviewerPath = path.join(trustedDir, 'fixture-reviewer.py')
  fs.writeFileSync(reviewerPath, REVIEWER_SCRIPT)
  const controlPath = path.join(workDir, 'reviewer-control.json')
  setControlMode(controlPath, 'pass')
  const pythonExecutable = process.env.WR_LIVE_PYTHON ?? 'python3'
  const reviewerArgv = [pythonExecutable, reviewerPath, controlPath]
  const userConfigPath = path.join(trustedDir, 'config.yaml')
  fs.writeFileSync(userConfigPath, userConfigYaml(reviewerArgv))

  // Stub Session Insight deployment serving the reader catalog.
  const sessionInsightServer = http.createServer((request, response) => {
    if (request.url === '/api/agents') {
      response.writeHead(200, { 'Content-Type': 'application/json' })
      response.end(
        JSON.stringify([
          { type: 'worktree-review', adapter_revision: 1, discovered: true },
        ]),
      )
      return
    }
    response.writeHead(200, { 'Content-Type': 'text/html' })
    response.end('<html><body>session insight stub</body></html>')
  })
  await new Promise<void>((resolve) => sessionInsightServer.listen(0, '127.0.0.1', resolve))
  const sessionInsightAddress = sessionInsightServer.address()
  if (sessionInsightAddress === null || typeof sessionInsightAddress === 'string') {
    throw new Error('session insight stub did not bind')
  }
  const sessionInsightUrl = `http://127.0.0.1:${sessionInsightAddress.port}`

  const port = 8900 + (process.pid % 400)
  const baseUrl = `http://127.0.0.1:${port}`
  const xdgStateHome = path.join(workDir, 'xdg-state')
  const journalRoot = path.join(xdgStateHome, 'worktree-review', 'sessions')
  const cacheHome = path.join(workDir, 'cache')
  fs.mkdirSync(cacheHome, { recursive: true })
  const serverProcess: ChildProcess = spawn(
    'uv',
    ['run', 'worktree-review-server'],
    {
      cwd: REPO_ROOT,
      env: {
        ...process.env,
        WORKTREE_REVIEW_WEB_DATABASE: path.join(workDir, 'web.sqlite'),
        WORKTREE_REVIEW_FRONTEND_DIST: path.join(REPO_ROOT, 'frontend', 'dist'),
        WORKTREE_REVIEW_BIND_PORT: String(port),
        XDG_STATE_HOME: xdgStateHome,
        XDG_CACHE_HOME: cacheHome,
        UV_CACHE_DIR: path.join(cacheHome, 'uv'),
        TMPDIR: workDir,
        WORKTREE_REVIEW_SESSION_INSIGHT_URL: sessionInsightUrl,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  )
  let serverLog = ''
  serverProcess.stdout?.on('data', (chunk) => {
    serverLog += String(chunk)
  })
  serverProcess.stderr?.on('data', (chunk) => {
    serverLog += String(chunk)
  })

  try {
    await waitForHealthz(baseUrl, 30_000)
  } catch (error) {
    serverProcess.kill()
    throw new Error(`${String(error)}\nserver log:\n${serverLog}`)
  }

  return {
    baseUrl,
    workDir,
    repositoryDir,
    controlPath,
    reviewPolicyPath,
    userConfigPath,
    journalRoot,
    sessionInsightUrl,
    pythonExecutable,
    reviewerArgv,
    cleanup: async () => {
      serverProcess.kill('SIGTERM')
      sessionInsightServer.close()
      await new Promise((resolve) => setTimeout(resolve, 300))
      fs.rmSync(workDir, { recursive: true, force: true })
    },
  }
}
