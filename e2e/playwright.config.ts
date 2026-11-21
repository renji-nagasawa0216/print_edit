import { defineConfig } from '@playwright/test'
import { BASE_URL, HOST_KEY } from './wt'

export default defineConfig({
  testDir: './tests',
  // 接続先ホストごとに分ける。共有 e2e で他 worktree の結果を消さない
  outputDir: `test-results/${HOST_KEY}`,
  // 条件付き並列。共有状態に触るTCは test.describe.serial() で隔離する（browser-test-gen.md）
  fullyParallel: true,
  workers: 4,
  retries: 0,
  // 1本あたりの上限。待ち方の欠陥（networkidle の待ち切り等）を fail として表面化させる
  timeout: 60_000,
  // スイート全体の上限。暴走を打ち切る。mokucolle #58 は待ち切りで70分走り続けた
  globalTimeout: 20 * 60_000,
  reporter: [['list'], ['html', { open: 'never', outputFolder: `playwright-report/${HOST_KEY}` }]],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    // 操作1回の上限。test の timeout とは別物（CSV 出力など正当に時間のかかる操作は test 側の timeout で吸収する）
    actionTimeout: 10_000,
    // print-edit の DOM 契約（ai_docs/documents/main/mock/*/inject.js）は data-key を使う
    // （QuartettCMS テンプレの name から変更）
    testIdAttribute: 'data-key',
    // worktree の https_url は自己署名証明書。これが無いと HTTPS 側が全滅する
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'tests', dependencies: ['setup'] },
  ],
})
