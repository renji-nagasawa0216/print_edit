// $E2E_DIR/wt.ts
import * as dotenv from 'dotenv'
import * as fs from 'fs'
import * as path from 'path'

/**
 * ベースURLの解決。優先順位は Step 0-0 が正本。
 *   1. <worktree>/.claude/wt-env.json の base_url   ← e2e が worktree 内にある場合の実値
 *   2. process.env.BASE_URL（CLI 指定 or test-accounts.local）
 *   3. http://localhost
 * 決定した値を process.env に書き戻す。dotenv は既存値を上書きしないため、
 * ワーカーや auth.setup.ts が別の値（test-accounts.local の BASE_URL）に差し替えない。
 */
dotenv.config({ path: path.resolve(__dirname, 'test-accounts.local') })

function resolveBaseURL(): string {
  const wtEnvPath = path.resolve(__dirname, '..', '.claude', 'wt-env.json')
  if (fs.existsSync(wtEnvPath)) {
    const wtEnv = JSON.parse(fs.readFileSync(wtEnvPath, 'utf-8'))
    if (wtEnv.base_url) return wtEnv.base_url
  }
  return process.env['BASE_URL'] ?? 'http://localhost'
}

export const BASE_URL = resolveBaseURL()
process.env['BASE_URL'] = BASE_URL

// 状態ファイルを分けるキー。Cookie のドメインと一致させるため、ホスト名そのものを使う
export const HOST_KEY = new URL(BASE_URL).hostname

export const authFile = (role: string): string =>
  path.resolve(__dirname, '.auth', HOST_KEY, `${role}.json`)

/**
 * issue 固有のアカウントは接続先ホストごとのファイルに置く（test-accounts.local・auth.setup.ts には書かない）。
 * e2e/accounts/<HOST_KEY>.local … 書式は test-accounts.local と同じ。同名キーはこちらが優先する。
 *   AUTH_SETUP_ROLES=<ロール,ロール>  setup で事前ログインするロール。省略時は *_EMAIL を持つ全ロール。
 */
const accountsPath = path.resolve(__dirname, 'accounts', `${HOST_KEY}.local`)
const hostAccounts = fs.existsSync(accountsPath)
  ? dotenv.parse(fs.readFileSync(accountsPath))
  : {}
Object.assign(process.env, hostAccounts)

export const HOST_ROLES: string[] = hostAccounts['AUTH_SETUP_ROLES'] !== undefined
  ? hostAccounts['AUTH_SETUP_ROLES'].split(',').map((r) => r.trim()).filter(Boolean)
  : Object.keys(hostAccounts)
      .filter((k) => k.endsWith('_EMAIL'))
      .map((k) => k.slice(0, -'_EMAIL'.length))
