/**
 * print-edit 用の配管 helper（/vf main）。前提データの値は持たない（値はシード側に置く）。
 *
 * TC ごとに 新しい --home を作り、シードを流し、専用ポートで serve を起動して baseURL をそのサーバへ向ける。
 *   1. home = <repo>/.vf/home/main_<RUN>/<TC ID>_r<retry>（毎回新しい。既存は消さない）
 *   2. sh .vf/seed/main.sh <TC ID> <home> pre            … 起動前（config.json・inbox・旧形式 DB）
 *   3. .venv/bin/print-edit serve --home <home> --port <p> … PATH 先頭に .vf/fakebin_main（偽 lp・lpstat・lpoptions）
 *   4. sh .vf/seed/main.sh <TC ID> <home> post <baseURL>  … 起動後（DB 行）
 *   5. teardown でプロセスグループごと停止
 * .vf/seed/main.sh のないチェックアウトは同梱の e2e/fixtures/seed.py で起動前に用意する。
 * シードの stdout に `PENDING <TC> <理由>` 行があれば .vf/pw/seed_status.tsv に記録する（データ未投入で落ちた TC の集計用）。
 *
 * 使い方（spec 側）: import { test, expect } from './helpers/home'。page.goto('/') はその TC 専用のサーバを開く。
 */
import { test as base, expect } from '@playwright/test'
import { spawn, spawnSync, type ChildProcess } from 'child_process'
import * as fs from 'fs'
import * as path from 'path'

const ROOT = path.resolve(__dirname, '..', '..', '..')
const SEED = path.join(ROOT, '.vf', 'seed', 'main.sh')
const BIN = path.join(ROOT, '.venv', 'bin', 'print-edit')
const FAKEBIN = path.join(ROOT, '.vf', 'fakebin_main')
const FIXTURE_BIN = path.join(ROOT, 'e2e', 'fixtures', 'fakebin')
const STATUS = path.join(ROOT, '.vf', 'pw', 'seed_status.tsv')
const RUN = process.env['PE_RUN_ID'] ?? new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)
// ワーカーごとに 20 ポートずつ割り当てる（8900〜。8765・8150 は範囲外）
const PORT_BASE = 8900
const PORTS_PER_WORKER = 20

function tcId(title: string): string {
  const id = title.split(' ')[0]
  if (!/^[A-Z]+-\d+/.test(id)) throw new Error(`seed failed: test タイトルから TC ID を取れない: ${title}`)
  return id
}

function runSeed(tc: string, home: string, phase: 'pre' | 'post', url = ''): void {
  const external = fs.existsSync(SEED)
  if (!external && phase === 'post') return
  const command = external ? 'sh' : path.join(ROOT, '.venv', 'bin', 'python')
  const args = external ? [SEED, tc, home, phase, url] : [path.join(ROOT, 'e2e', 'fixtures', 'seed.py'), tc, home]
  const r = spawnSync(command, args, { cwd: ROOT, encoding: 'utf-8', timeout: 30_000 })
  if (r.status !== 0) {
    throw new Error(`seed failed: ${tc} ${phase} exit=${r.status} ${(r.stderr || r.stdout || '').trim().split('\n')[0] ?? ''}`)
  }
  const pending = (r.stdout ?? '').split('\n').filter((l) => l.startsWith('PENDING '))
  if (pending.length) {
    fs.mkdirSync(path.dirname(STATUS), { recursive: true })
    fs.appendFileSync(STATUS, pending.map((l) => `${RUN}\t${phase}\t${l.slice('PENDING '.length)}`).join('\n') + '\n')
  }
}

const alive = (proc: ChildProcess): boolean => proc.exitCode === null && proc.signalCode === null

async function waitReady(url: string, proc: ChildProcess, log: () => string): Promise<void> {
  const deadline = Date.now() + 30_000
  while (Date.now() < deadline) {
    if (!alive(proc)) throw new Error(`EXITED ${log()}`)
    try {
      const res = await fetch(url + '/')
      // 応答が前の TC のサーバ（終了処理中）からでないことを、自分のプロセスの生存で確かめる
      if (res.ok) {
        await new Promise((r) => setTimeout(r, 300))
        if (alive(proc)) return
        throw new Error(`EXITED ${log()}`)
      }
    } catch (e) {
      if ((e as Error).message.startsWith('EXITED')) throw e
      // 起動待ち
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error(`ECONNREFUSED serve が 30 秒以内に応答しない: ${url} ${log()}`)
}

// 終了を待ってからポートを手放す（待たないと同じワーカーの次の TC が同じポートで起動に失敗する）
async function stop(proc: ChildProcess): Promise<void> {
  if (!proc.pid || !alive(proc)) return
  const exited = new Promise<void>((r) => proc.once('exit', () => r()))
  try {
    process.kill(-proc.pid, 'SIGTERM')
  } catch {
    return // 既に終了
  }
  await Promise.race([exited, new Promise((r) => setTimeout(r, 10_000))])
}

export const test = base.extend<{ peHome: string, seedCase: string }>({
  seedCase: ['', { option: true }],
  peHome: async ({}, use, testInfo) => {
    const directory = path.join(ROOT, '.vf', 'home', `main_${RUN}`)
    fs.mkdirSync(directory, { recursive: true })
    const home = fs.mkdtempSync(path.join(directory, `${tcId(testInfo.title)}_r${testInfo.retry}_`))
    await use(home)
  },
  baseURL: [
    async ({ peHome, seedCase }, use, testInfo) => {
      const tc = seedCase || tcId(testInfo.title)
      runSeed(tc, peHome, 'pre')
      const first = PORT_BASE + testInfo.parallelIndex * PORTS_PER_WORKER
      let proc: ChildProcess | undefined
      let url = ''
      for (let port = first; port < first + PORTS_PER_WORKER; port++) {
        url = `http://127.0.0.1:${port}`
        let out = ''
        const p = spawn(BIN, ['serve', '--home', peHome, '--port', String(port)], {
          cwd: ROOT,
          detached: true,
          env: {
            ...process.env,
            PATH: `${FAKEBIN}:${FIXTURE_BIN}:${process.env['PATH'] ?? ''}`,
            PE_TEST_LP_LOG: path.join(peHome, 'lp.log'),
          },
          stdio: ['ignore', 'pipe', 'pipe'],
        })
        p.stdout?.on('data', (d) => (out += d))
        p.stderr?.on('data', (d) => (out += d))
        fs.writeFileSync(path.join(peHome, 'serve.pid'), String(p.pid ?? ''))
        try {
          await waitReady(url, p, () => out.slice(-300))
          proc = p
          break
        } catch (e) {
          await stop(p)
          if (/address already in use|Errno 48/i.test(out)) continue
          throw new Error(`ECONNREFUSED serve 起動失敗 (${tc}): ${(e as Error).message}`)
        }
      }
      if (!proc) throw new Error(`ECONNREFUSED 空きポートが無い: ${first}〜${first + PORTS_PER_WORKER - 1}`)
      try {
        runSeed(tc, peHome, 'post', url)
        await use(url)
      } finally {
        await stop(proc)
      }
    },
    { scope: 'test', timeout: 60_000 },
  ],
})

export { expect }
