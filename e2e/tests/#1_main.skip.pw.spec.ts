import type { Page } from '@playwright/test'
import { test, expect } from './helpers/home'

async function open(page: Page, name: string) {
  await page.goto('/')
  await page.locator('nav').getByRole('button', { name, exact: true }).click()
}

async function confirmNative(page: Page, click: () => Promise<void>) {
  const message = new Promise<string>(resolve => page.once('dialog', async dialog => {
    const text = dialog.message()
    await dialog.accept()
    resolve(text)
  }))
  await click()
  return message
}

for (const id of ['N-05', 'E-38']) {
  test(`${id} 取り込みのみで4画像を処理し、reviewも登録待ちに残す`, async ({ page }) => {
    await open(page, '取り込み')
    await expect(page.getByText('未取り込み 4 件', { exact: true })).toBeVisible()
    await expect(page.getByText(/^フォルダ監視: (稼働中|停止中|不明|非対応)$/)).toBeVisible()
    await expect(page.getByText('最終取り込み なし')).toBeVisible()
    await page.getByRole('button', { name: '取込&作成', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('対象: 未取り込みの画像 4 件')
    await page.getByRole('button', { name: 'キャンセル' }).click()
    expect(await confirmNative(page, () => page.getByRole('button', { name: '取り込みのみ' }).click())).toBe('4 件処理しました')
    await expect(page.locator('#queue .ccard')).toHaveCount(4)
    await expect(page.locator('#queue .badge')).toHaveCount(0)
    await expect(page.getByText('未取り込み 0 件', { exact: true })).toBeVisible()
    await expect(page.getByText('最終取り込み なし')).toHaveCount(0)
    const cards = await (await page.request.get('/api/cards?reg=pending&status=review')).json()
    expect(cards).toHaveLength(1)
    await expect(page.locator('#queue .ccard').filter({ hasText: cards[0].source_name })).toHaveCount(1)
    expect(await (await page.request.get('/api/sheets')).json()).toEqual([])
  })
}

for (const [id, verb, count, pending, master] of [
  ['N-12', '登録', 3, 1, 3], ['N-13', '破棄', 2, 2, 0], ['B-05', '登録', 1, 0, 1],
] as const) {
  test(`${id} 登録待ちの一括${verb}で対象と件数を保持`, async ({ page }) => {
    await open(page, '取り込み')
    const before = await (await page.request.get('/api/cards?reg=pending')).json()
    for (let i = 0; i < count; i++) await page.locator('#queue .ccard').nth(i).getByRole('checkbox').check()
    const text = await confirmNative(page, () => page.getByRole('button', { name: `一括${verb}（${count}件）` }).click())
    expect(text).toContain(`${count}件`)
    await expect(page.locator('#bulk-result')).toContainText(`成功 ${count}件`)
    await expect(page.locator('#queue .ccard')).toHaveCount(pending)
    const after = await (await page.request.get('/api/cards?reg=pending')).json()
    expect(after.map((c: {id: number}) => c.id)).toEqual(before.slice(count).map((c: {id: number}) => c.id))
    if (!pending) await expect(page.getByText('登録待ちの名刺はありません')).toBeVisible()
    await page.locator('nav').getByRole('button', { name: '名刺マスタ' }).click()
    await expect(page.locator('#master .ccard')).toHaveCount(master)
    const registered = await (await page.request.get('/api/cards?reg=master')).json()
    expect(registered.map((c: {id: number}) => c.id)).toEqual(verb === '登録' ? before.slice(0, count).map((c: {id: number}) => c.id) : [])
  })
}

for (const [id, verb, count] of [
  ['N-85', '印刷', 3], ['N-87', '破棄', 2], ['N-88', '破棄', 1], ['B-15', '印刷', 1],
] as const) {
  test(`${id} 印刷待ちの一括${verb}、確認と結果`, async ({ page }) => {
    await open(page, '印刷待ち')
    const master = await (await page.request.get('/api/cards?reg=master')).json()
    for (let i = 1; i <= count; i++) await page.getByLabel(`選択 #${i}`, { exact: true }).check()
    await page.getByRole('button', { name: `一括${verb}（${count}件）` }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toContainText(`${count}件`)
    await dialog.getByRole('button', { name: `${verb}する` }).click()
    const result = page.locator('#bulk-result')
    await expect(result).toContainText(`成功 ${count}件`)
    await expect(result.getByRole('listitem')).toHaveCount(count)
    if (verb === '印刷') {
      await expect(result.getByRole('listitem').filter({ hasText: '送信なし（出力先 pdf）' })).toHaveCount(count)
      await expect(page.locator('#held .card')).toHaveCount(5)
    } else {
      await expect(page.locator('#held .card')).toHaveCount(5 - count)
      const discarded = await (await page.request.get('/api/sheets?status=discarded')).json()
      expect(discarded.map((s: {id: number}) => s.id).sort()).toEqual(Array.from({ length: count }, (_, i) => i + 1))
      expect(await (await page.request.get('/api/cards?reg=master')).json()).toEqual(master)
      await page.locator('nav').getByRole('button', { name: '履歴' }).click()
      await page.locator('#history .job').filter({ hasText: 'scan_a.jpg' }).getByRole('button', { name: '詳細' }).click()
      for (const s of discarded) {
        await expect(page.locator(`#history [data-sheet="${s.id}"] .tag`)).toHaveText('discarded')
      }
    }
  })
}

test('N-62 印刷済みシートを履歴から調整して同じPDFを上書き', async ({ page }) => {
  await open(page, '履歴')
  const sheets = async () => (await (await page.request.get('/api/sheets')).json()) as { id: number, pdf_path: string }[]
  const before = await sheets()
  const path = before.find(s => s.id === 2)!.pdf_path
  const bytes = await (await page.request.get('/files/' + path)).body()
  const job = page.locator('#history .job').filter({ hasText: 'scan_a.jpg' })
  await job.getByRole('button', { name: '詳細' }).click()
  await job.locator('[data-sheet="2"]').getByRole('button', { name: '調整する' }).click()
  await expect(page.locator('#adjust-banner')).toContainText('シート 2')
  await expect(page.getByLabel('新規として保存')).toBeChecked()
  await expect(page.locator('#pdf details[open]')).toHaveCount(0)
  await expect(page.locator('#pdf details')).toHaveCount(2)
  await page.locator('#pdf .ir input[type=number]').first().fill('3')
  await page.getByRole('radio', { name: /上書き保存/ }).check()
  const text = await confirmNative(page, () => page.getByRole('button', { name: '保存して作成' }).click())
  expect(text).toContain('印刷済み')
  await expect(page.locator('#pdf-msg')).toContainText('作成しました')
  const after = await sheets()
  expect(after.length).toBe(before.length)
  expect(after.find(s => s.id === 2)!.pdf_path).toBe(path)
  const saved = await (await page.request.get('/api/sheets/2/adjust')).json()
  expect(saved.items[0].count).toBe(3)
  expect(await (await page.request.get('/files/' + path)).body()).not.toEqual(bytes)
})

test('B-14 印刷待ち0件では一括操作バーを隠す', async ({ page }) => {
  await open(page, '印刷待ち')
  await expect(page.getByText('印刷待ちのシートはありません')).toBeVisible()
  await expect(page.locator('#held .bulkbar')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /一括印刷|一括破棄/ })).toHaveCount(0)
})
