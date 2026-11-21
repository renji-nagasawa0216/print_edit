/**
 * #1_main  正本: ai_docs/specs/#1_main.md
 * 骨格は pw-tc.sh が生成。test タイトル・SKIP 行・@spec 行は変えない（pw-check.sh が照合する）
 */
import { test, expect } from './helpers/home'
import type { Locator, Page, Response } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'

// ログイン無しのアプリ（bt_config）。ロールは前提データの記号で、authFile は使わない。
// 前提データは helper（home.ts）が TC ごとに .vf/seed/main.sh で投入する。

// 構造 CSS はここに集約する。出典は DOM 契約（ai_docs/documents/main/mock/*/inject.js）。
const CSS = {
  tabs: '#tabs',
  queue: '#queue .ccard', // 登録待ち一覧のカード
  master: '#master .ccard', // 名刺マスタ一覧のカード
  held: '#held .card', // 印刷待ち一覧の行
  preset: '.preset-list li', // 設定作成の既定値一覧
  legacyKeys: '[data-key=timing],[data-key=duplicate_count],[data-key=fill]',
}

const BULK_REG = /一括登録|選んだものを登録/ // 正本は「一括登録」、モックは「選んだものを登録（n件）」
const BULK_DISCARD = /一括破棄|選んだものを破棄/
const BULK_PRINT = /一括印刷|選んだものを印刷/

const tab = (page: Page, name: string) => page.locator(CSS.tabs).getByRole('button', { name, exact: true })
const queue = (page: Page) => page.locator(CSS.queue)
const master = (page: Page) => page.locator(CSS.master)
const held = (page: Page) => page.locator(CSS.held)
const presetItems = (page: Page) => page.locator(CSS.preset)
const ingestBtn = (page: Page) => page.getByRole('button', { name: '取込&作成', exact: true })
const createBtn = (page: Page) => page.getByRole('button', { name: '作成', exact: true })
const overText = (page: Page, n: number) => page.getByText(new RegExp(`${n}\\s*枚超過`)).first()
// 「使う名刺」の行（候補の追加行も .ir なので、枚数入力を持つ行だけに絞る）
const itemRows = (page: Page) =>
  page.getByRole('group', { name: '使う名刺' }).locator('.ir').filter({ has: page.locator('input[type=number]') })
const qty = (page: Page, i: number) => itemRows(page).nth(i).locator('input[type=number]')
// D2 のマスタ名刺: C1=scan_a.jpg で名前あり、C2=scan_b.jpg、C3=scan_a.jpg で名前なし
const c1 = (page: Page) => master(page).filter({ hasText: 'scan_a.jpg' }).filter({ hasNotText: '（名前なし）' })
const c2 = (page: Page) => master(page).filter({ hasText: 'scan_b.jpg' })
const c3 = (page: Page) => master(page).filter({ hasText: '（名前なし）' })
const nameValues = (page: Page) =>
  page.locator('#master input[type=text]').evaluateAll((els) => els.map((e) => (e as HTMLInputElement).value))
const bulkBtn = (page: Page, name: RegExp) => page.getByRole('button', { name })

// プレビュー・容量取得の POST は除き、保存・削除などの書き込み応答だけを待つ
const isWrite = (r: Response) =>
  ['POST', 'PUT', 'DELETE'].includes(r.request().method()) && !/preview|capacity/.test(r.url())

async function openTab(page: Page, name: string) {
  await page.goto('/')
  await tab(page, name).click()
}

function nextAlert(page: Page): Promise<string> {
  return new Promise((resolve) => {
    page.once('dialog', (d) => {
      resolve(d.message())
      void d.accept()
    })
  })
}

async function runIngest(page: Page, preset?: string): Promise<string> {
  await ingestBtn(page).click()
  if (preset) await page.getByLabel('使う既定値').selectOption({ label: preset })
  const msg = nextAlert(page)
  await page.getByRole('button', { name: '実行', exact: true }).click()
  return msg
}

async function clickWrite(page: Page, target: Locator) {
  await Promise.all([page.waitForResponse(isWrite), target.click()])
}

async function saveName(page: Page, card: Locator, value: string) {
  await card.locator('input[type=text]').fill(value)
  await clickWrite(page, card.getByRole('button', { name: '名前を保存' }))
}

async function search(page: Page, value: string) {
  await page.getByLabel('検索', { exact: true }).fill(value)
}

async function pdfFrom(page: Page, pick: (p: Page) => Locator[]) {
  await openTab(page, '名刺マスタ')
  const cards = pick(page)
  for (const c of cards) await c.getByRole('checkbox').check()
  await page.getByRole('button', { name: `PDF 作成（${cards.length}件）`, exact: true }).click()
}

async function pdfFromAll(page: Page): Promise<number> {
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  const n = await master(page).count()
  for (let i = 0; i < n; i++) await master(page).nth(i).getByRole('checkbox').check()
  await page.getByRole('button', { name: `PDF 作成（${n}件）`, exact: true }).click()
  return n
}

function collectKeys(v: unknown, out: string[] = []): string[] {
  if (v && typeof v === 'object') {
    for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
      out.push(k)
      collectKeys(x, out)
    }
  }
  return out
}

// SKIP: P-01 - 性能テストのため除外
// SKIP: P-02 - 性能テストのため除外
// SKIP: P-03 - 性能テストのため除外
// SKIP: T-01 - タイミング・不整合のため除外
// SKIP: T-02 - タイミング・不整合のため除外
// SKIP: T-03 - タイミング・不整合のため除外
// SKIP: T-04 - タイミング・不整合のため除外
// SKIP: X-01 - 自動実行不可（lp による実機送信を伴う）
// SKIP: X-02 - 自動実行不可（lp 失敗・PDF 生成失敗を起こすにはコードの一時改変かプリンター故障が必要）
// SKIP: X-03 - 自動実行不可（lp 失敗の再現にコード一時改変が必要。実印刷を伴う）
// SKIP: X-04 - 自動実行不可（lp 実送信を伴う）
// SKIP: X-05 - 自動実行不可（送信中（sending）状態を作る DB 直接操作・競合再現が必要）
// SKIP: X-06 - 自動実行不可（プロセス強制終了の再現が必要）
// SKIP: X-07 - 自動実行不可（複数プロセスの同時実行・タイミング制御が必要）
// SKIP: X-08 - 自動実行不可（launchd・外部フォルダ監視（時間経過）が必要）
// SKIP: X-09 - 自動実行不可（ブラウザ操作でなく CLI）
// SKIP: X-10 - 自動実行不可（既存テスト（tests/unit/test_cli_pipeline.py・test_spec_11_3.py・test_spec_11_2.py・test_api.py・tests/acceptance/test_acceptance_extra.py）の書き換えは開発側作業）
// SKIP: X-11 - 自動実行不可（取り込み実行（フォルダ監視）経路）
// SKIP: X-12 - 自動実行不可（プロセス強制終了・DB 直接操作が必要）
// SKIP: X-13 - 自動実行不可（実機の紙出力・印刷結果の目視が必要な範囲を含む）
// SKIP: X-14 - 自動実行不可（プリンター機種依存（実プリンタ情報））
// SKIP: X-15 - 自動実行不可（UI は作成ボタンを無効にして送信させない。新規保存 API のパスが正本に無く、ブラウザ側からは不正値を送る手段を確定できない）

// role: 未判定（前提条件から決められない）
test('N-01 [M1] 上部タブの構成と順', async ({ page }) => {
  // @spec L274
  await page.goto('/')
  // 表示順は DOM 順
  // @spec L274
  await expect(page.locator(CSS.tabs).getByRole('button')).toHaveText(['取り込み', '名刺マスタ', 'PDF 作成', '履歴', '印刷待ち', '設定作成', '全体設定'])
  // @spec L274
  await expect(tab(page, '面付けプレビュー')).toHaveCount(0)
  // @spec L274
  await expect(tab(page, '要確認')).toHaveCount(0)
})

test('N-02 [M2] 「今すぐ取り込み」が「取込&作成」に置換', async ({ page }) => {
  // @spec L275
  await page.goto('/')
  // @spec L275
  await expect(ingestBtn(page)).toBeVisible()
  // @spec L275
  await expect(page.getByRole('button', { name: '今すぐ取り込み' })).toHaveCount(0)
})

test('N-03 [M2] 取込&作成ダイアログの説明文と選択肢', async ({ page }) => {
  // @spec L276
  await page.goto('/')
  await ingestBtn(page).click()
  // @spec L276
  await expect(page.getByText('取り込んだ名刺は登録待ちに入ります（マスタには自動で登録しません）')).toBeVisible()
  // 選択肢の順は DOM 順
  // @spec L276
  await expect(page.getByLabel('使う既定値').locator('option')).toHaveText(['既定', '名刺大', '枠だけ'])
  // @spec L276
  await expect(page.getByLabel('使う既定値').locator('option:checked')).toHaveText('既定')
})

test('N-04 [M2] 前回選んだ既定値が初期値', async ({ page }) => {
  // @spec L277
  await page.goto('/')
  await runIngest(page, '名刺大')
  await ingestBtn(page).click()
  // @spec L277
  await expect(page.getByLabel('使う既定値').locator('option:checked')).toHaveText('名刺大')
  // config.json の前回選択キー名が正本に無いため、保存先の確認は画面の初期値のみ
})

// SKIP: N-05 - 生成不可（取り込みのみを実行するボタンが DOM 契約に無い。06_ingest は「画像を選んで取り込む」のファイル選択のみ）
// @spec L278

test('N-06 [M4] 登録待ち一覧に全カードを載せる', async ({ page }) => {
  // @spec L279
  await openTab(page, '取り込み')
  // 並びは DOM 順（P1, P2=scan_a.jpg / P3, P4=scan_b.jpg）
  // @spec L279
  await expect(queue(page)).toHaveCount(4)
  for (const i of [0, 1]) {
    // @spec L279
    await expect(queue(page).nth(i)).toContainText('scan_a.jpg')
    // @spec L279
    await expect(queue(page).nth(i)).toContainText('2026-11-01')
  }
  for (const i of [2, 3]) {
    // @spec L279
    await expect(queue(page).nth(i)).toContainText('scan_b.jpg')
    // @spec L279
    await expect(queue(page).nth(i)).toContainText('2026-11-02')
  }
})

test('N-07 [M4] 登録待ち一覧の画像は lazy 縮小表示', async ({ page }) => {
  // @spec L280
  await openTab(page, '取り込み')
  await queue(page).first().waitFor()
  for (const img of await queue(page).locator('img').all()) {
    // @spec L280
    await expect(img).toHaveAttribute('loading', 'lazy')
  }
})

// SKIP: N-08 - 生成不可（切り出し画像が180度回ったことを判定する画像比較の helper が無い）
// @spec L281

test('N-09 [M5,M6] 登録待ちで破棄（個別）', async ({ page }) => {
  // @spec L282
  await openTab(page, '取り込み')
  // 並びは DOM 順。P2 は2番目
  await clickWrite(page, queue(page).nth(1).getByRole('button', { name: '破棄', exact: true }))
  // @spec L282
  await expect(queue(page)).toHaveCount(3)
  await tab(page, '名刺マスタ').click()
  // @spec L282
  await expect(master(page)).toHaveCount(0)
})

test('N-10 [M5,M6] review カードの「登録」が承認を兼ねる', async ({ page }) => {
  // @spec L283
  await openTab(page, '取り込み')
  // 並びは DOM 順。P4（review）は4番目
  await clickWrite(page, queue(page).nth(3).getByRole('button', { name: '登録' }))
  // @spec L283
  await expect(queue(page)).toHaveCount(3)
  // @spec L283
  await expect(page.getByRole('button', { name: '承認' })).toHaveCount(0)
  await tab(page, '名刺マスタ').click()
  // @spec L283
  await expect(master(page)).toHaveCount(1)
  // @spec L283
  await expect(master(page).first()).toContainText('scan_b.jpg')
})

test('N-11 [M6] 個別登録', async ({ page }) => {
  // @spec L284
  await openTab(page, '取り込み')
  // 並びは DOM 順。P1 は先頭
  await clickWrite(page, queue(page).first().getByRole('button', { name: '登録' }))
  // @spec L284
  await expect(queue(page)).toHaveCount(3)
  // @spec L284
  await expect(queue(page).filter({ hasText: 'scan_a.jpg' })).toHaveCount(1)
  // @spec L284
  await expect(queue(page).filter({ hasText: 'scan_b.jpg' })).toHaveCount(2)
  await tab(page, '名刺マスタ').click()
  // @spec L284
  await expect(master(page)).toHaveCount(1)
  // @spec L284
  await expect(master(page).first()).toContainText('scan_a.jpg')
})

// SKIP: N-12 - 生成不可（件数つき確認が native confirm か DOM ダイアログか正本・DOM 契約に無く、確認文言を取得できない）
// @spec L285

// SKIP: N-13 - 生成不可（件数つき確認が native confirm か DOM ダイアログか正本・DOM 契約に無く、確認文言を取得できない）
// @spec L286

// SKIP: N-15 - 生成不可（アプリの再起動が必要。helper（home.ts）に serve を再起動する手段が無い）
// @spec L288

test('N-17 [M7] 移行分バッジは登録待ちの間だけ', async ({ page }) => {
  // @spec L290
  await openTab(page, '取り込み')
  await clickWrite(page, queue(page).first().getByRole('button', { name: '登録' }))
  await tab(page, '名刺マスタ').click()
  await master(page).first().waitFor()
  // @spec L290
  await expect(master(page).filter({ hasText: '移行分' })).toHaveCount(0)
  // @spec L290
  await expect(master(page).filter({ hasText: '使用済み' })).toHaveCount(0)
})

test('N-18 [M4,M7] 使用済みバッジは sheet_cards から導出（J18 反映。取込&作成を使わず、P1 を含むシートを用意する）', async ({ page }) => {
  // @spec L291
  await openTab(page, '取り込み')
  await queue(page).first().waitFor()
  // 並びは DOM 順。P1 は先頭
  // @spec L291
  await expect(queue(page).first()).toContainText('使用済み')
  for (const i of [1, 2, 3]) {
    // @spec L291
    await expect(queue(page).nth(i)).not.toContainText('使用済み')
  }
})

test('N-19 [M8] 名刺名の付与・保存', async ({ page }) => {
  // @spec L292
  await openTab(page, '名刺マスタ')
  await c3(page).first().waitFor()
  await saveName(page, c3(page), '  山田  ')
  await page.reload()
  await tab(page, '名刺マスタ').click()
  // @spec L292
  await expect.poll(() => nameValues(page)).toContain('山田')
})

test('N-20 [M8] 名前未設定の表示', async ({ page }) => {
  // @spec L293
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  // @spec L293
  await expect(c3(page)).toHaveCount(1)
})

test('N-21 [M8] 重複名を許す', async ({ page }) => {
  // @spec L294
  await openTab(page, '名刺マスタ')
  await c3(page).first().waitFor()
  await saveName(page, c3(page), 'Alpha')
  await page.reload()
  await tab(page, '名刺マスタ').click()
  // @spec L294
  await expect.poll(async () => (await nameValues(page)).filter((v) => v === 'Alpha').length).toBe(2)
})

test('N-22 [M9] 検索: 名前の部分一致', async ({ page }) => {
  // @spec L295
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, 'lph')
  // @spec L295
  await expect(master(page)).toHaveCount(1)
  // @spec L295
  await expect(master(page).first().locator('input[type=text]')).toHaveValue('Alpha')
})

test('N-23 [M9] 検索: 元ファイル名の部分一致', async ({ page }) => {
  // @spec L296
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, 'scan_b')
  // @spec L296
  await expect(master(page)).toHaveCount(1)
  // @spec L296
  await expect(master(page).first().locator('input[type=text]')).toHaveValue('鈴木太郎')
})

test('N-24 [M9] 検索: 取込日（YYYY-MM-DD 部分一致）', async ({ page }) => {
  // @spec L297
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, '2026-11')
  // @spec L297
  await expect(master(page)).toHaveCount(3)
})

test('N-25 [M9] 検索: 英字の大小を区別しない', async ({ page }) => {
  // @spec L298
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, 'ALPHA')
  // @spec L298
  await expect(master(page)).toHaveCount(1)
  // @spec L298
  await expect(master(page).first().locator('input[type=text]')).toHaveValue('Alpha')
})

test('N-26 [M9] 検索: 空欄は全件', async ({ page }) => {
  // @spec L299
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, 'lph')
  await master(page).nth(1).waitFor({ state: 'detached' })
  await search(page, '')
  // @spec L299
  await expect(master(page)).toHaveCount(3)
})

// SKIP: N-27 - 生成不可（履歴詳細のシート行 S1 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L300

// SKIP: N-28 - 生成不可（履歴詳細のシート行 S2 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L301

test('N-29 [M10] 復元画面は無い', async ({ page }) => {
  // @spec L302
  page.on('dialog', (d) => void d.accept())
  await openTab(page, '名刺マスタ')
  await c1(page).first().waitFor()
  await clickWrite(page, c1(page).getByRole('button', { name: '削除' }))
  await c1(page).first().waitFor({ state: 'detached' })
  for (const name of ['取り込み', '名刺マスタ', 'PDF 作成', '履歴', '印刷待ち', '設定作成', '全体設定']) {
    await tab(page, name).click()
    // @spec L302
    await expect(page.getByRole('button', { name: /復元|元に戻す/ })).toHaveCount(0)
  }
})

test('N-30 [M11,M17] マスタ選択→PDF作成（枚数初期値）', async ({ page }) => {
  // @spec L303
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  // @spec L303
  await expect(itemRows(page)).toHaveCount(2)
  // 行の並びは DOM 順（選択順）
  // @spec L303
  await expect(qty(page, 0)).toHaveValue('1')
  // @spec L303
  await expect(qty(page, 1)).toHaveValue('1')
})

test('N-31 [M11,M17] PDF作成画面内から検索して名刺を追加', async ({ page }) => {
  // @spec L304
  await openTab(page, 'PDF 作成')
  await page.getByLabel('マスタから追加').fill('鈴木')
  const candidate = page.getByRole('group', { name: '使う名刺' }).locator('.ir').filter({ hasText: '鈴木太郎' })
  await candidate.getByRole('button', { name: '追加' }).click()
  // @spec L304
  await expect(itemRows(page)).toHaveCount(1)
  // @spec L304
  await expect(itemRows(page).first()).toContainText('鈴木太郎')
})

// SKIP: N-32 - 生成不可（設定作成の「新規」操作と cards_per_sheet の入力欄が DOM 契約に無い。04 のモックは cards_per_sheet を描いていない）
// @spec L305

// SKIP: N-33 - 生成不可（並べ順の保存後に「枠だけ」「既定」の全項目値を比べる入力欄の DOM 契約が無い。cards_per_sheet・補正欄のラベルがスキーマ由来）
// @spec L306

test('N-34 [M12] 既定値の削除', async ({ page }) => {
  // @spec L307
  page.on('dialog', (d) => void d.accept())
  await openTab(page, '設定作成')
  await presetItems(page).filter({ hasText: '枠だけ' }).click()
  await clickWrite(page, page.locator('.preset-list').getByRole('button', { name: '削除', exact: true }))
  // @spec L307
  await expect(presetItems(page)).toHaveCount(2)
  // @spec L307
  await expect(presetItems(page).filter({ hasText: '枠だけ' })).toHaveCount(0)
})

test('N-35 [M12,M14] 既定値に含まれる項目', async ({ page }) => {
  // @spec L308
  await openTab(page, '設定作成')
  // @spec L308
  await expect(page.getByRole('group', { name: '補正' })).toBeVisible()
  // @spec L308
  await expect(page.getByRole('group', { name: '面付け' })).toBeVisible()
  // @spec L308
  await expect(page.getByLabel('まとめ方')).toBeVisible()
  // @spec L308
  await expect(page.getByText('1名刺あたりの枚数')).toBeVisible()
  // @spec L308
  await expect(page.getByLabel('並べ順')).toBeVisible()
  // @spec L308
  await expect(page.getByLabel('カラーモード')).toHaveCount(0)
  // @spec L308
  await expect(page.getByLabel('部数')).toHaveCount(0)
  // @spec L308
  await expect(page.getByLabel('倍率補正')).toHaveCount(0)
  // @spec L308
  await expect(page.getByLabel('プリンター')).toHaveCount(0)
})

// SKIP: N-36 - 生成不可（スロット図の枠・容量表示の要素が DOM 契約に無い。previewNodes() の出力要素が未定義）
// @spec L309

// SKIP: N-37 - 生成不可（全体設定の各項目ラベルが /api/config/schema 由来で、DOM 契約・正本に文言が無い）
// @spec L310

test('N-39 [M15] 旧 timing=duplicate の変換', async ({ page }) => {
  // @spec L312
  await openTab(page, '設定作成')
  // @spec L312
  await expect(page.getByLabel('まとめ方').locator('option:checked')).toHaveText('複数名刺1PDF')
  // @spec L312
  await expect(page.getByRole('group', { name: '並べ方' }).getByRole('spinbutton')).toHaveValue('3')
  // @spec L312
  await expect(page.getByLabel('並べ順').locator('option:checked')).toHaveText('行優先')
})

test('N-40 [M15] 旧 timing=per_scan の変換', async ({ page }) => {
  // @spec L313
  await openTab(page, '設定作成')
  // @spec L313
  await expect(page.getByLabel('まとめ方').locator('option:checked')).toHaveText('複数名刺1PDF')
  // @spec L313
  await expect(page.getByRole('group', { name: '並べ方' }).getByRole('spinbutton')).toHaveValue('1')
  // @spec L313
  await expect(page.getByLabel('並べ順').locator('option:checked')).toHaveText('行優先')
})

test('N-41 [M15] 旧 timing=fill の変換', async ({ page }) => {
  // @spec L314
  await openTab(page, '設定作成')
  // @spec L314
  await expect(page.getByLabel('まとめ方').locator('option:checked')).toHaveText('複数名刺1PDF')
  // @spec L314
  await expect(page.getByRole('group', { name: '並べ方' }).getByRole('spinbutton')).toHaveValue('1')
  // @spec L314
  await expect(page.getByLabel('並べ順').locator('option:checked')).toHaveText('行優先')
})

test('N-42 [M15] 旧 duplicate_count=null（空）の変換', async ({ page }) => {
  // @spec L315
  await openTab(page, '設定作成')
  // @spec L315
  await expect(page.getByLabel('まとめ方').locator('option:checked')).toHaveText('複数名刺1PDF')
  // @spec L315
  await expect(page.getByRole('group', { name: '並べ方' }).getByRole('radio', { name: '全部埋める' })).toBeChecked()
  // @spec L315
  await expect(page.getByLabel('並べ順').locator('option:checked')).toHaveText('行優先')
})

test('N-43 [M15] 移行前 config.json の退避', async ({ page, peHome }) => {
  // @spec L316
  await page.goto('/')
  const bakPath = path.join(peHome, 'config.json.bak')
  // @spec L316
  expect(fs.existsSync(bakPath)).toBe(true)
  const bak = JSON.parse(fs.readFileSync(bakPath, 'utf-8')) as { print: { timing: string; duplicate_count: number } }
  // @spec L316
  expect(bak.print.timing).toBe('duplicate')
  // @spec L316
  expect(bak.print.duplicate_count).toBe(3)
  const keys = collectKeys(JSON.parse(fs.readFileSync(path.join(peHome, 'config.json'), 'utf-8')))
  // @spec L316
  expect(keys).not.toContain('fill')
  // @spec L316
  expect(keys).not.toContain('timing')
  // @spec L316
  expect(keys).not.toContain('duplicate_count')
})

test('N-44 [M15] 旧設定の UI 廃止', async ({ page }) => {
  // @spec L317
  await page.goto('/')
  for (const name of ['設定作成', '全体設定', 'PDF 作成']) {
    await tab(page, name).click()
    // @spec L317
    await expect(page.locator(CSS.legacyKeys)).toHaveCount(0)
  }
})

test('N-45 [M17] PDF作成: マスタから複数名刺（取り込みをまたぐ）', async ({ page }) => {
  // @spec L318
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  // @spec L318
  await expect(itemRows(page)).toHaveCount(2)
  // @spec L318
  await expect(itemRows(page).filter({ hasText: 'scan_a.jpg' })).toHaveCount(1)
  // @spec L318
  await expect(itemRows(page).filter({ hasText: 'scan_b.jpg' })).toHaveCount(1)
})

// SKIP: N-46 - 生成不可（プレビューのスロット番号と名刺の対応を読む DOM が正本・DOM 契約に無い。モックは SVG の自前描画で実装との一致が未確定）
// @spec L319

// SKIP: N-47 - 生成不可（プレビューのスロット番号と名刺の対応を読む DOM が正本・DOM 契約に無い）
// @spec L320

// SKIP: N-48 - 生成不可（スロットをクリックして差し替えるパネルと、各スロットの割当を読む DOM が正本・DOM 契約に無い）
// @spec L321

// SKIP: N-49 - 生成不可（スロット7へ差し替えた結果を読む DOM と、保存後のスロット配置を確認する手段が無い）
// @spec L322

// SKIP: N-50 - 生成不可（保存後の sheet_cards 行数を読む手段（DB 直読み helper・API パス）が無い）
// @spec L323

test('N-51 [M17] ちょうど容量は作成可', async ({ page }) => {
  // @spec L324
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('5')
  await qty(page, 1).fill('5')
  // @spec L324
  await expect(page.getByText(/枚超過/)).toHaveCount(0)
  // @spec L324
  await expect(createBtn(page)).toBeEnabled()
})

test('N-52 [M17] 全部埋める: 割り切れる', async ({ page }) => {
  // @spec L325
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await page.getByRole('group', { name: '並べ方' }).getByRole('radio', { name: '全部埋める' }).check()
  // @spec L325
  await expect(qty(page, 0)).toHaveValue('5')
  // @spec L325
  await expect(qty(page, 1)).toHaveValue('5')
  // @spec L325
  await expect(page.getByText(/枚超過/)).toHaveCount(0)
})

test('N-53 [M17] 全部埋める: 割り切れない', async ({ page }) => {
  // @spec L326
  const n = await pdfFromAll(page)
  expect(n).toBe(3)
  await page.getByRole('group', { name: '並べ方' }).getByRole('radio', { name: '全部埋める' }).check()
  for (const i of [0, 1, 2]) {
    // @spec L326
    await expect(qty(page, i)).toHaveValue('3')
  }
  // 余り1スロットの位置（並べ順の末尾側が空）はスロット→名刺の DOM が無く確認しない
})

test('N-54 [M17] 全部埋める: 名刺数が容量超', async ({ page }) => {
  // @spec L327
  const n = await pdfFromAll(page)
  expect(n).toBe(11)
  await page.getByRole('group', { name: '並べ方' }).getByRole('radio', { name: '全部埋める' }).check()
  for (const row of await itemRows(page).all()) {
    // @spec L327
    await expect(row.locator('input[type=number]')).toHaveValue('1')
  }
  // @spec L327
  await expect(overText(page, 1)).toBeVisible()
  // @spec L327
  await expect(createBtn(page)).toBeDisabled()
})

// SKIP: N-55 - 生成不可（自動割当の再計算結果を読むスロット→名刺の DOM が正本・DOM 契約に無い）
// @spec L328

// SKIP: N-56 - 生成不可（保存後の sheets 件数・sheet_cards 行数を読む手段（DB 直読み helper・API パス）が無い）
// @spec L329

// SKIP: N-57 - 生成不可（保存後の sheets 件数・sheet_cards 行数を読む手段（DB 直読み helper・API パス）が無い）
// @spec L330

// SKIP: N-58 - 生成不可（1名刺1PDF の名刺切り替え UI は J20=A でモックが無く、DOM 契約に無い）
// @spec L331

// SKIP: N-59 - 生成不可（プレビュー内の名刺画像要素が DOM 契約に無い。モックは SVG の data URL で「名刺の画像 URL」を確認できない）
// @spec L332

// SKIP: N-60 - 生成不可（拡大表示・ホイール拡大縮小の対象要素が DOM 契約に無い。モックの #mock-zoom はモック専用）
// @spec L333

// SKIP: N-61 - 生成不可（保存後の sheets 件数・sheet_cards.slot・スナップショットを読む手段（DB 直読み helper・API パス）が無い）
// @spec L334

// SKIP: N-62 - 生成不可（履歴詳細のシート行 S2 を識別する情報と、上書き確認の形式（native confirm か DOM か）が正本・DOM 契約に無い）
// @spec L335

// SKIP: N-63 - 生成不可（履歴詳細のシート行 S2 を識別する情報と、上書き確認の形式が正本・DOM 契約に無い）
// @spec L336

// SKIP: N-64 - 生成不可（履歴詳細のシート行 S2 を識別する情報と、上書き確認の形式が正本・DOM 契約に無い）
// @spec L337

// SKIP: N-65 - 生成不可（履歴詳細のシート行 S1 を識別する情報が DOM 契約に無い）
// @spec L338

// SKIP: N-66 - 生成不可（「上書き保存」の確認の形式が正本・DOM 契約に無く、保存後の値の比較に使う補正欄のラベルがスキーマ由来）
// @spec L339

// SKIP: N-67 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L340

// SKIP: N-68 - 生成不可（読み込み後に値が反映される補正・面付け欄のラベルがスキーマ由来で DOM 契約に無い）
// @spec L341

test('N-69 [M21] 手動 PDF: auto_print=OFF・出力先 lp は印刷待ちへ', async ({ page }) => {
  // @spec L342
  page.on('dialog', (d) => void d.accept())
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).waitFor()
  await clickWrite(page, createBtn(page))
  await tab(page, '印刷待ち').click()
  // @spec L342
  await expect(held(page)).toHaveCount(1)
  // lp へ送られないことは偽 lp（fakebin）の記録を読む手段が無く確認しない
})

test('N-70 [M21] 手動 PDF: 出力先 pdf は保存のみ', async ({ page }) => {
  // @spec L343
  page.on('dialog', (d) => void d.accept())
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).waitFor()
  await clickWrite(page, createBtn(page))
  await tab(page, '印刷待ち').click()
  // @spec L343
  await expect(page.getByText('印刷待ちのシートはありません')).toBeVisible()
  // @spec L343
  await expect(held(page)).toHaveCount(0)
  // PDF ファイルの保存先パスが正本に無く、ファイルの存在は確認しない
})

test('N-71 [M22] 取込&作成: 登録待ち名刺で PDF を作る', async ({ page }) => {
  // @spec L344
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // @spec L344
  expect(msg).toContain('PDF 1件')
  await tab(page, '名刺マスタ').click()
  // @spec L344
  await expect(master(page)).toHaveCount(0)
})

test('N-72 [M22,M4] 取込&作成: 使った名刺は登録待ち＋使用済みバッジ', async ({ page }) => {
  // @spec L345
  await page.goto('/')
  await runIngest(page, '既定')
  await tab(page, '取り込み').click()
  // 取り込んだ3枚は使用済み、名刺でない画像（review）は登録待ちに残るがバッジなし
  // @spec L345
  await expect(queue(page)).toHaveCount(4)
  // @spec L345
  await expect(queue(page).filter({ hasText: '使用済み' })).toHaveCount(3)
})

test('N-73 [M22] 取込&作成: 使った名刺を後からマスタ登録して PDF 作成に使える', async ({ page }) => {
  // @spec L346
  await page.goto('/')
  await runIngest(page, '既定')
  await tab(page, '取り込み').click()
  await queue(page).first().waitFor()
  await clickWrite(page, queue(page).filter({ hasText: '使用済み' }).first().getByRole('button', { name: '登録' }))
  await tab(page, '名刺マスタ').click()
  // @spec L346
  await expect(master(page)).toHaveCount(1)
  await master(page).first().getByRole('checkbox').check()
  await page.getByRole('button', { name: 'PDF 作成（1件）', exact: true }).click()
  // @spec L346
  await expect(itemRows(page)).toHaveCount(1)
})

test('N-74 [M22] 取込&作成: 超過は順序を保って次の PDF へ', async ({ page }) => {
  // @spec L347
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // 1つ目に先頭10枚・2つ目に残り2枚という中身は、PDF の枚数（alert の PDF 件数）でのみ確認する
  // @spec L347
  expect(msg).toBe('取り込み 12件・PDF 2件を作成しました')
})

// SKIP: N-75 - 生成不可（取込&作成が PDF を置く jobs 配下のディレクトリと、連番を数える対象 sheets/ が正本に無い）
// @spec L348

test('N-76 [M22] 取込&作成: review カードは PDF に含めず登録待ちに残す', async ({ page }) => {
  // @spec L349
  await page.goto('/')
  await runIngest(page, '既定')
  await tab(page, '取り込み').click()
  // @spec L349
  await expect(queue(page)).toHaveCount(4)
  // PDF に使われた（使用済み）のは review でない3枚だけ。残る1枚が review
  // @spec L349
  await expect(queue(page).filter({ hasNotText: '使用済み' })).toHaveCount(1)
})

test('N-77 [M23] 全体設定: 自動取り込み方式の選択', async ({ page }) => {
  // @spec L350
  page.on('dialog', (d) => void d.accept())
  await openTab(page, '全体設定')
  await page.getByRole('radio', { name: /^取込&作成/ }).check()
  await page.getByLabel('使う既定値').selectOption({ label: '名刺大' })
  await clickWrite(page, page.getByRole('button', { name: '保存', exact: true }))
  await page.reload()
  await tab(page, '全体設定').click()
  // @spec L350
  await expect(page.getByRole('radio', { name: /^取込&作成/ })).toBeChecked()
  // @spec L350
  await expect(page.getByLabel('使う既定値').locator('option:checked')).toHaveText('名刺大')
  await page.getByRole('radio', { name: '取り込みのみ' }).check()
  // @spec L350
  await expect(page.getByRole('radio', { name: '取り込みのみ' })).toBeChecked()
})

// SKIP: N-79 - 生成不可（履歴詳細のシート行 S2・S3 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L352

// SKIP: N-80 - 生成不可（履歴詳細のシート行 S1・S4 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L353

// SKIP: N-81 - 生成不可（履歴詳細のシート行 S1〜S4 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L354

// SKIP: N-83 - 生成不可（履歴詳細のシート行 S6 を識別する情報が DOM 契約に無い）
// @spec L356

// SKIP: N-84 - 生成不可（job_id なしシート（S7）の履歴一覧での行の構造（「PDF 作成」表記の要素）が DOM 契約に無い）
// @spec L357

// SKIP: N-85 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果一覧の要素が正本・DOM 契約に無い）
// @spec L358

test('N-86 [M27,M28] 印刷待ち: 全選択', async ({ page }) => {
  // @spec L359
  await openTab(page, '印刷待ち')
  await held(page).first().waitFor()
  // @spec L359
  await expect(held(page)).toHaveCount(5)
  await page.getByLabel('全選択').check()
  for (const row of await held(page).all()) {
    // @spec L359
    await expect(row.getByRole('checkbox')).toBeChecked()
  }
  // 確認ダイアログの「5件」は確認の形式が正本・DOM 契約に無く確認しない
})

// SKIP: N-87 - 生成不可（件数つき確認が native confirm か DOM ダイアログか正本・DOM 契約に無く、確認文言を取得できない）
// @spec L360

// SKIP: N-88 - 生成不可（件数つき確認が native confirm か DOM ダイアログか正本・DOM 契約に無い）
// @spec L361

test('N-89 [M28] 行内の「印刷する」「破棄」の併置', async ({ page }) => {
  // @spec L362
  await openTab(page, '印刷待ち')
  await held(page).first().waitFor()
  for (const row of await held(page).all()) {
    // @spec L362
    await expect(row.getByRole('button', { name: '印刷する' })).toBeVisible()
    // @spec L362
    await expect(row.getByRole('button', { name: '破棄', exact: true })).toBeVisible()
  }
  // @spec L362
  await expect(bulkBtn(page, BULK_PRINT)).toBeVisible()
  // @spec L362
  await expect(bulkBtn(page, BULK_DISCARD)).toBeVisible()
  // @spec L362
  await expect(page.getByLabel('全選択')).toBeVisible()
})

// SKIP: N-90 - 生成不可（基準コミット 7aacd05 の画像バイト列との比較が必要で、基準画像の入手・新規保存 API のパスが正本に無い）
// @spec L363

// SKIP: N-91 - 生成不可（名刺名保存・一括登録・削除・既定値保存の各 API パスが正本に無く、直接送る宛先を確定できない）
// @spec L364

test('N-92 [M31,M8,M20] 名刺名・既定値名は textNode で描画', async ({ page }) => {
  // @spec L365
  let alerts = 0
  page.on('dialog', (d) => {
    alerts += 1
    void d.dismiss()
  })
  await openTab(page, '名刺マスタ')
  await c3(page).first().waitFor()
  const cardCount = await master(page).count()
  const payload = '<img src=x onerror=alert(1)>'
  await saveName(page, c3(page), payload)
  await page.reload()
  await tab(page, '名刺マスタ').click()
  // @spec L365
  await expect.poll(() => nameValues(page)).toContain(payload)
  // @spec L365
  expect(alerts).toBe(0)
  // 名刺ごとのサムネイル以外に img が増えない
  // @spec L365
  await expect(page.locator('#master img')).toHaveCount(cardCount)
  // 既定値名の描画は「別名で保存」の名前入力の形式が正本に無く確認しない
})

// SKIP: N-93 - 生成不可（基準コミット 7aacd05 と同じ拒否ステータスの値が正本に無い。マスタ画像の /files URL も DOM 契約に無い）
// @spec L366

test('N-95 [M2] 取込&作成ダイアログの実行ボタン名', async ({ page }) => {
  // @spec L368
  await page.goto('/')
  await ingestBtn(page).click()
  // @spec L368
  await expect(page.getByRole('button', { name: '実行', exact: true })).toBeVisible()
})

test('N-96 [M22] 取込&作成の結果表示（1件以上。文言と空白を確定）', async ({ page }) => {
  // @spec L369
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // 数字の前は半角空白、後ろは空白なし
  // @spec L369
  expect(msg).toBe('取り込み 3件・PDF 1件を作成しました')
})

test('N-97 [M4] 登録待ち一覧の並び順', async ({ page }) => {
  // @spec L370
  await openTab(page, '取り込み')
  await queue(page).first().waitFor()
  // 並びは DOM 順。取込日時の古い順（scan_a.jpg が先）。同一取り込み内の idx 順は ID を読む DOM が無く確認しない
  for (const [i, file] of ['scan_a.jpg', 'scan_a.jpg', 'scan_b.jpg', 'scan_b.jpg'].entries()) {
    // @spec L370
    await expect(queue(page).nth(i)).toContainText(file)
  }
})

test('N-98 [M8] 名刺マスタ一覧の並び順（登録待ちと同じ）', async ({ page }) => {
  // @spec L371
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  // 並びは DOM 順。C1=Alpha, C3=名前なし, C2=鈴木太郎
  for (const [i, name] of ['Alpha', '', '鈴木太郎'].entries()) {
    // @spec L371
    await expect(master(page).nth(i).locator('input[type=text]')).toHaveValue(name)
  }
})

// SKIP: N-99 - 生成不可（履歴一覧の行（ジョブ行・「PDF 作成」行）の構造と作成日時の表示位置が DOM 契約に無い）
// @spec L372

test('N-100 [M28] 印刷待ち一覧の並び順', async ({ page }) => {
  // @spec L373
  await openTab(page, '印刷待ち')
  await held(page).first().waitFor()
  // 並びは DOM 順。作成日時の古い順（H1=2026-11-05 … H5=2026-11-09）
  for (const i of [0, 1, 2, 3, 4]) {
    // @spec L373
    await expect(held(page).nth(i)).toContainText(`2026-11-0${5 + i}`)
  }
})

// SKIP: N-101 - 生成不可（履歴詳細のシート行 S2・S7 を識別する情報と、上書き確認の形式が正本・DOM 契約に無い）
// @spec L374

// SKIP: N-102 - 生成不可（履歴詳細のシート行 S2 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L375

// SKIP: N-103 - 生成不可（履歴詳細のシート行 S3 を識別する情報（シート番号・状態）が DOM 契約に無い）
// @spec L376

test('N-104 [M22,M4] 取込&作成は既存の登録待ちを拾わない（J18）', async ({ page }) => {
  // @spec L377
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // @spec L377
  expect(msg).toContain('取り込み 3件・PDF 1件')
  await tab(page, '取り込み').click()
  await queue(page).first().waitFor()
  // 並びは DOM 順。既存の P1〜P4 が先（取込日時が古い）、新しい3枚が後
  // @spec L377
  await expect(queue(page)).toHaveCount(7)
  for (const i of [0, 1, 2, 3]) {
    // @spec L377
    await expect(queue(page).nth(i)).not.toContainText('使用済み')
  }
  for (const i of [4, 5, 6]) {
    // @spec L377
    await expect(queue(page).nth(i)).toContainText('使用済み')
  }
})

test('N-105 [M22] 取込&作成の結果表示: n に review を含める', async ({ page }) => {
  // @spec L378
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // @spec L378
  expect(msg).toBe('取り込み 4件・PDF 1件を作成しました')
})

test('N-106 [M9] 検索結果の並び順（名刺マスタ一覧と同じ）', async ({ page }) => {
  // @spec L379
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, '2026-11')
  // @spec L379
  await expect(master(page)).toHaveCount(3)
  // 並びは DOM 順。C1=Alpha, C3=名前なし, C2=鈴木太郎
  for (const [i, name] of ['Alpha', '', '鈴木太郎'].entries()) {
    // @spec L379
    await expect(master(page).nth(i).locator('input[type=text]')).toHaveValue(name)
  }
})

test('E-01 [M2,M12] 取込&作成: 前回の既定値が削除済み', async ({ page }) => {
  // @spec L384
  page.on('dialog', (d) => void d.accept())
  await openTab(page, '設定作成')
  await presetItems(page).filter({ hasText: '名刺大' }).click()
  await clickWrite(page, page.locator('.preset-list').getByRole('button', { name: '削除', exact: true }))
  await tab(page, '取り込み').click()
  await ingestBtn(page).click()
  // @spec L384
  await expect(page.getByLabel('使う既定値').locator('option:checked')).toHaveText('既定')
})

test('E-02 [M4] 登録待ち0件の文言', async ({ page }) => {
  // @spec L385
  await openTab(page, '取り込み')
  // @spec L385
  await expect(page.getByText('登録待ちの名刺はありません')).toBeVisible()
})

// SKIP: E-03 - 生成不可（P4 の card id を読む DOM・API が無く、存在しない id への POST と区別できない）
// @spec L386

test('E-04 [M6] 未選択で一括ボタン無効（登録待ち）', async ({ page }) => {
  // @spec L387
  await openTab(page, '取り込み')
  await queue(page).first().waitFor()
  // @spec L387
  await expect(bulkBtn(page, BULK_REG)).toBeDisabled()
  // @spec L387
  await expect(bulkBtn(page, BULK_DISCARD)).toBeDisabled()
})

test('E-07 [M9] 検索0件', async ({ page }) => {
  // @spec L390
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, 'zzzz')
  // @spec L390
  await expect(page.getByText('該当する名刺はありません')).toBeVisible()
})

// SKIP: E-08 - 生成不可（期待結果が「削除ボタン無効、または拒否」の二択で、拒否が完了したことを待つ信号（応答・表示）が正本に無く、判定が競合する）
// @spec L391

// SKIP: E-09 - 生成不可（名前入力が無効か保存が拒否されるかが正本で未確定で、拒否の完了を待つ信号が無い）
// @spec L392

// SKIP: E-10 - 生成不可（設定作成の「新規」操作の入力形式（名前入力・保存ボタンの構成）が DOM 契約に無い）
// @spec L393

// SKIP: E-11 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L394

// SKIP: E-12 - 生成不可（cards_per_sheet の入力欄と、フォームの msg 要素（class=err）の位置が DOM 契約に無い）
// @spec L395

// SKIP: E-13 - 生成不可（削除が拒否されたことを待つ信号と、理由の表示形式（alert か msg か）が正本に無く、判定が競合する）
// @spec L396

test('E-14 [M16,M15] 旧キーを PUT /api/config に送る', async ({ page, peHome }) => {
  // @spec L397
  await page.goto('/')
  const cfgPath = path.join(peHome, 'config.json')
  const before = fs.readFileSync(cfgPath, 'utf-8')
  // ページ内 fetch で旧キー print.timing を含めて送る
  const status = await page.evaluate(async () => {
    const cfg = (await (await fetch('/api/config')).json()) as { print: Record<string, unknown> }
    const body = { ...cfg, print: { ...cfg.print, timing: 'per_scan' } }
    const res = await fetch('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    return res.status
  })
  // @spec L397
  expect(status).toBe(422)
  // @spec L397
  expect(fs.readFileSync(cfgPath, 'utf-8')).toBe(before)
})

test('E-15 [M17] PDF作成: 名刺0件で作成不可', async ({ page }) => {
  // @spec L398
  await openTab(page, 'PDF 作成')
  // @spec L398
  await expect(createBtn(page)).toBeDisabled()
})

test('E-16 [M17] PDF作成: 合計枚数0で作成不可', async ({ page }) => {
  // @spec L399
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).fill('0')
  // @spec L399
  await expect(createBtn(page)).toBeDisabled()
})

test('E-17 [M17] PDF作成: 超過で作成不可・赤字表示', async ({ page }) => {
  // @spec L400
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('7')
  await qty(page, 1).fill('6')
  // 赤字の色値は正本に無く、超過表示と作成ボタン無効のみ確認する
  // @spec L400
  await expect(overText(page, 3)).toBeVisible()
  // @spec L400
  await expect(createBtn(page)).toBeDisabled()
})

// SKIP: E-18 - 生成不可（スロット8の差し替え操作と、枚数変更時の確認の形式が正本・DOM 契約に無い）
// @spec L401

// SKIP: E-19 - 生成不可（履歴詳細のシート行 S1 を識別する情報が DOM 契約に無い）
// @spec L402

// SKIP: E-20 - 生成不可（保存方法の「上書き」が「無効」か「存在しない」かが正本・DOM 契約で未確定（08 のモックは調整時のみ保存方法を描く））
// @spec L403

// SKIP: E-21 - 生成不可（保存後の sheets 件数を読む手段（DB 直読み helper・API パス）が無い）
// @spec L404

// SKIP: E-23 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L406

// SKIP: E-24 - 生成不可（sheets が増えないことを読む手段（DB 直読み helper・API パス・履歴の行構造）が DOM 契約に無い）
// @spec L407

test('E-26 [M24] 旧ジョブ単位再印刷 API の廃止', async ({ page }) => {
  // @spec L409
  await page.goto('/')
  const res = await page.request.post('/api/jobs/x/reprint')
  // @spec L409
  expect(res.ok()).toBe(false)
})

test('E-28 [M27,M28] 未選択で一括印刷・一括破棄ボタン無効', async ({ page }) => {
  // @spec L411
  await openTab(page, '印刷待ち')
  await held(page).first().waitFor()
  // @spec L411
  await expect(bulkBtn(page, BULK_PRINT)).toBeDisabled()
  // @spec L411
  await expect(bulkBtn(page, BULK_DISCARD)).toBeDisabled()
})

// SKIP: E-30 - 生成不可（アプリの再起動が必要。helper（home.ts）に serve を再起動する手段が無い）
// @spec L413

test('E-31 [M22] 取込&作成の結果表示（0件）', async ({ page }) => {
  // @spec L414
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // @spec L414
  expect(msg).toBe('取り込む対象がありませんでした')
  // sheets が増えないことを読む手段が無く、alert の文言のみ確認する
})

test('E-32 [M17] 枚数=0（その名刺の入力不正）', async ({ page }) => {
  // @spec L415
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('0')
  await qty(page, 1).fill('3')
  // @spec L415
  await expect(createBtn(page)).toBeDisabled()
})

test('E-33 [M17] 枚数が負数', async ({ page }) => {
  // @spec L416
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('-1')
  await qty(page, 1).fill('3')
  // @spec L416
  await expect(createBtn(page)).toBeDisabled()
})

test('E-34 [M17] 枚数が小数', async ({ page }) => {
  // @spec L417
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('1.5')
  await qty(page, 1).fill('3')
  // @spec L417
  await expect(createBtn(page)).toBeDisabled()
})

test('E-35 [M17] 枚数が空', async ({ page }) => {
  // @spec L418
  await pdfFrom(page, (p) => [c1(p), c2(p)])
  await qty(page, 0).fill('')
  await qty(page, 1).fill('3')
  // @spec L418
  await expect(createBtn(page)).toBeDisabled()
})

// SKIP: E-36 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L419

// SKIP: E-38 - 生成不可（取り込みのみを実行するボタンが DOM 契約に無い。06_ingest は「画像を選んで取り込む」のファイル選択のみ）
// @spec L421

test('E-39 [M21,M17] 手動 PDF: 超過で作成不可のとき sheets・印刷待ちが増えない', async ({ page }) => {
  // @spec L422
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).fill('11')
  // @spec L422
  await expect(overText(page, 1)).toBeVisible()
  // @spec L422
  await expect(createBtn(page)).toBeDisabled()
  await tab(page, '印刷待ち').click()
  // @spec L422
  await expect(page.getByText('印刷待ちのシートはありません')).toBeVisible()
})

test('B-01 [M8] 名刺名 100字', async ({ page }) => {
  // @spec L429
  await openTab(page, '名刺マスタ')
  await c3(page).first().waitFor()
  const name100 = 'あ'.repeat(100)
  await saveName(page, c3(page), name100)
  await page.reload()
  await tab(page, '名刺マスタ').click()
  // @spec L429
  await expect.poll(() => nameValues(page)).toContain(name100)
})

test('B-02 [M8,M19] 名刺名 101字', async ({ page }) => {
  // @spec L430
  await openTab(page, '名刺マスタ')
  await c3(page).first().waitFor()
  const alertMsg = nextAlert(page)
  await c3(page).locator('input[type=text]').fill('あ'.repeat(101))
  await c3(page).getByRole('button', { name: '名前を保存' }).click()
  const alertText = await alertMsg
  // @spec L430
  expect(alertText).toContain('失敗:')
  await page.reload()
  await tab(page, '名刺マスタ').click()
  // @spec L430
  await expect(c3(page)).toHaveCount(1)
})

// SKIP: B-03 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L431

// SKIP: B-04 - 生成不可（「別名で保存」の名前入力の形式（prompt か画面内入力か）が正本・DOM 契約に無い）
// @spec L432

// SKIP: B-05 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果表示の要素が正本・DOM 契約に無い）
// @spec L433

test('B-06 [M17] 容量−1 / 容量 / 容量+1', async ({ page }) => {
  // @spec L434
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).fill('9')
  // @spec L434
  await expect(createBtn(page)).toBeEnabled()
  await qty(page, 0).fill('10')
  // @spec L434
  await expect(createBtn(page)).toBeEnabled()
  await qty(page, 0).fill('11')
  // @spec L434
  await expect(overText(page, 1)).toBeVisible()
  // @spec L434
  await expect(createBtn(page)).toBeDisabled()
})

test('B-07 [M17] 名刺1種・枚数1（最小）', async ({ page }) => {
  // @spec L435
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).fill('1')
  // @spec L435
  await expect(createBtn(page)).toBeEnabled()
  // @spec L435
  await expect(page.getByText(/枚超過/)).toHaveCount(0)
})

test('B-08 [M17] 全部埋める: 名刺1件', async ({ page }) => {
  // @spec L436
  await pdfFrom(page, (p) => [c1(p)])
  await page.getByRole('group', { name: '並べ方' }).getByRole('radio', { name: '全部埋める' }).check()
  // @spec L436
  await expect(qty(page, 0)).toHaveValue('10')
})

test('B-09 [M17] 全部埋める: 名刺数=容量', async ({ page }) => {
  // @spec L437
  const n = await pdfFromAll(page)
  expect(n).toBe(10)
  for (const row of await itemRows(page).all()) {
    // @spec L437
    await expect(row.locator('input[type=number]')).toHaveValue('1')
  }
  // @spec L437
  await expect(page.getByText(/枚超過/)).toHaveCount(0)
  // @spec L437
  await expect(createBtn(page)).toBeEnabled()
})

// SKIP: B-10 - 生成不可（スロット1・10 をクリックして差し替えるパネルの DOM が正本・DOM 契約に無い）
// @spec L438

test('B-11 [M22] 取込&作成: ちょうど容量の枚数（J18 反映）', async ({ page }) => {
  // @spec L439
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // 「PDF が1つだけ」は alert の PDF 件数で確認する（sheets 件数を読む手段が無い）
  // @spec L439
  expect(msg).toBe('取り込み 10件・PDF 1件を作成しました')
})

test('B-12 [M22] 取込&作成: 容量+1（J18 反映）', async ({ page }) => {
  // @spec L440
  await page.goto('/')
  const msg = await runIngest(page, '既定')
  // 2つ目がスロット1の1枚という配置は、スロット→名刺の DOM が無く確認しない
  // @spec L440
  expect(msg).toBe('取り込み 11件・PDF 2件を作成しました')
})

// SKIP: B-13 - 生成不可（履歴一覧で scan_z.jpg のジョブ行を特定する要素が DOM 契約に無い。ジョブ行はジョブ ID を表示する）
// @spec L441

test('B-14 [M28] 印刷待ち0件', async ({ page }) => {
  // @spec L442
  await openTab(page, '印刷待ち')
  // @spec L442
  await expect(page.getByText('印刷待ちのシートはありません')).toBeVisible()
})

// SKIP: B-15 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果一覧の要素が正本・DOM 契約に無い）
// @spec L443

test('B-16 [M9] 検索: 日付の一部（月のみ）', async ({ page }) => {
  // @spec L444
  await openTab(page, '名刺マスタ')
  await master(page).first().waitFor()
  await search(page, '11-02')
  // @spec L444
  await expect(master(page)).toHaveCount(1)
  // @spec L444
  await expect(master(page).first().locator('input[type=text]')).toHaveValue('鈴木太郎')
})

test('B-17 [M21,M29] 手動 PDF: 出力先 pdf かつ auto_print=OFF（組み合わせの境界）', async ({ page }) => {
  // @spec L445
  page.on('dialog', (d) => void d.accept())
  await pdfFrom(page, (p) => [c1(p)])
  await qty(page, 0).waitFor()
  await clickWrite(page, createBtn(page))
  await tab(page, '印刷待ち').click()
  // @spec L445
  await expect(page.getByText('印刷待ちのシートはありません')).toBeVisible()
  // @spec L445
  await expect(held(page)).toHaveCount(0)
  // PDF ファイルの保存・lp へ送られないことは、保存先パスと偽 lp の記録を読む手段が無く確認しない
})

test.describe('role: D4', () => {
  // ロール D4 は前提データの記号（旧形式の --home）。ログイン無しのアプリのため認証は使わない

  test('N-14 [M7] 移行: discarded 以外が登録待ちへ', async ({ page }) => {
    // @spec L287
    await openTab(page, '取り込み')
    // @spec L287
    await expect(queue(page)).toHaveCount(5)
    // @spec L287
    await expect(queue(page).filter({ hasText: '移行分' })).toHaveCount(5)
  })

  test('N-16 [M7] 移行前に db.sqlite3 のコピー', async ({ page, peHome }) => {
    // @spec L289
    await page.goto('/')
    // WAL・journal の付随ファイルはコピーに数えない
    const copies = fs.readdirSync(peHome).filter((f) => f.startsWith('db.sqlite3') && f !== 'db.sqlite3' && !/-(wal|shm|journal)$/.test(f))
    // @spec L289
    expect(copies).toHaveLength(1)
  })

  test('N-38 [M15] 設定移行: 現在の設定が既定値「既定」へ', async ({ page }) => {
    // @spec L311
    await openTab(page, '設定作成')
    // @spec L311
    await expect(presetItems(page)).toHaveCount(1)
    // @spec L311
    await expect(presetItems(page).first()).toContainText('既定')
    // 旧 config の補正・面付け・全体設定の個別値は控えが正本に無いため確認しない
  })

  test('N-78 [M23,M15] 移行時の自動取り込み既定', async ({ page }) => {
    // @spec L351
    await openTab(page, '全体設定')
    // @spec L351
    await expect(page.getByRole('radio', { name: /^取込&作成/ })).toBeChecked()
    // @spec L351
    await expect(page.getByLabel('使う既定値').locator('option:checked')).toHaveText('既定')
  })

  // SKIP: N-94 - 生成不可（移行前の printer_name・lp_options 等の控え値と、全体設定の各項目ラベルが正本・DOM 契約に無い）
  // @spec L367

})

test.describe('role: S7', () => {
  // ロール S7 は前提データの記号（job_id なしシート）。ログイン無しのアプリのため認証は使わない

  // SKIP: N-82 - 生成不可（履歴一覧で S7 の行を特定する要素と、復元値（枚数・配置・補正・面付け）を読む DOM が正本・DOM 契約に無い）
  // @spec L355

})

test.describe('role: P1', () => {
  // ロール P1 は前提データの記号（登録待ちの名刺）。ログイン無しのアプリのため認証は使わない

  // SKIP: E-05 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果表示の要素が正本・DOM 契約に無い）
  // @spec L388

  // SKIP: E-37 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果表示の要素が正本・DOM 契約に無い）
  // @spec L420

})

test.describe('role: C1', () => {
  // ロール C1 は前提データの記号（名前ありのマスタ名刺）。ログイン無しのアプリのため認証は使わない

  test('E-06 [M8] 名前の空欄（trim 後空）は未設定に戻る', async ({ page }) => {
    // @spec L389
    await openTab(page, '名刺マスタ')
    await c1(page).first().waitFor()
    await saveName(page, c1(page), '   ')
    await page.reload()
    await tab(page, '名刺マスタ').click()
    // C1 と元から名前なしの C3 の2件
    // @spec L389
    await expect(c3(page)).toHaveCount(2)
  })

})

test.describe('role: PDF', () => {
  // ロール PDF は前提データの記号（PDF 作成画面を開く利用者）。ログイン無しのアプリのため認証は使わない

  test('E-22 [M19,M10] 保存時にマスタ削除済み名刺（失敗通知を確定）', async ({ page }) => {
    // @spec L405
    await pdfFrom(page, (p) => [c1(p)])
    await qty(page, 0).waitFor()
    // 別タブ（同じ context の別 page）から C1 をマスタ削除する
    const other = await page.context().newPage()
    other.on('dialog', (d) => void d.accept())
    await openTab(other, '名刺マスタ')
    await c1(other).first().waitFor()
    await clickWrite(other, c1(other).getByRole('button', { name: '削除' }))
    const alertMsg = nextAlert(page)
    await createBtn(page).click()
    const alertText = await alertMsg
    // @spec L405
    expect(alertText).toContain('失敗:')
    // sheets が増えないことを読む手段が無く、失敗通知のみ確認する
  })

})

test.describe('role: S1', () => {
  // ロール S1 は前提データの記号（held のシート）。ログイン無しのアプリのため認証は使わない

  // SKIP: E-25 - 生成不可（S4 の再印刷 API のパス・シート ID が正本に無く、状態を読む画面の DOM 契約も無い）
  // @spec L408

})

test.describe('role: H2', () => {
  // ロール H2 は前提データの記号（印刷待ちのシート H2）。ログイン無しのアプリのため認証は使わない

  // SKIP: E-27 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果一覧の要素が正本・DOM 契約に無い）
  // @spec L410

  // SKIP: E-29 - 生成不可（件数つき確認が native confirm か DOM ダイアログか、結果一覧の要素が正本・DOM 契約に無い）
  // @spec L412

})

test.describe('role: S3', () => {
  // ロール S3 は前提データの記号（error のシート）。ログイン無しのアプリのため認証は使わない

  // SKIP: E-40 - 生成不可（履歴詳細のシート行 S3 を識別する情報と、復元値（枚数・配置・補正・面付け）を読む DOM が正本・DOM 契約に無い）
  // @spec L423

})

test.describe('role: JB', () => {
  // ロール JB は前提データの記号（ジョブ JB）。ログイン無しのアプリのため認証は使わない

  // SKIP: E-41 - 生成不可（履歴一覧でジョブ JB の行と状態表示を特定する要素が DOM 契約に無い）
  // @spec L424

})

test.describe('role: S4', () => {
  // ロール S4 は前提データの記号（discarded のシート）。ログイン無しのアプリのため認証は使わない

  // SKIP: B-18 - 生成不可（履歴詳細のシート行 S4・S7 を識別する情報と、復元値を読む DOM が正本・DOM 契約に無い）
  // @spec L446

})

