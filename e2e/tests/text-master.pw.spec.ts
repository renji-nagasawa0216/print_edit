import type { Locator, Page } from '@playwright/test'
import { test, expect } from './helpers/home'

// N-19 の前提データ D2 にある名刺「Alpha」を使用する。home とDBはケースごとに独立する。
test.use({ seedCase: 'N-19' })

const masterTab = (page: Page) => page.locator('nav').getByRole('button', { name: '名刺マスタ', exact: true })
const cardNamed = (page: Page, name: string) =>
  page.locator('#master .ccard').filter({ has: page.getByText(name, { exact: true }) })

async function moveHandle(page: Page, handle: Locator, dx: number, dy: number) {
  await handle.scrollIntoViewIfNeeded()
  const bounds = await handle.boundingBox()
  if (!bounds) throw new Error('テキストボックスの操作ハンドルが表示されていません')
  const x = bounds.x + bounds.width / 2
  const y = bounds.y + bounds.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x + dx, y + dy, { steps: 6 })
  await page.mouse.up()
}

test('TEXT-01 テキスト入りマスタを作成・再編集してPDFに配置する', async ({ page }) => {
  await page.goto('/')
  await masterTab(page).click()
  const parent = cardNamed(page, 'Alpha')
  await parent.getByRole('button', { name: '文字入りマスタを作成' }).click()
  const editor = page.getByRole('dialog')
  const name = editor.getByLabel('マスタ名', { exact: true })
  const content = editor.getByLabel('文字', { exact: true })
  const left = editor.getByLabel('左（mm）', { exact: true })
  const top = editor.getByLabel('上（mm）', { exact: true })
  const save = editor.getByRole('button', { name: '保存', exact: true })

  await name.fill('営業用')
  await content.fill('SALES')
  await editor.getByLabel('文字サイズ（pt）').fill('12')
  const x0 = Number(await left.inputValue())
  const y0 = Number(await top.inputValue())
  await moveHandle(page, editor.locator('.text-box-handle').first(), 28, 18)
  const x1 = Number(await left.inputValue())
  const y1 = Number(await top.inputValue())
  expect(x1).toBeGreaterThan(x0)
  expect(y1).toBeGreaterThan(y0)
  await save.click()
  await expect(editor).toHaveCount(0)

  await page.reload()
  await masterTab(page).click()
  const child = cardNamed(page, '営業用')
  await child.getByRole('button', { name: '文字を編集' }).click()
  await expect(content).toHaveValue('SALES')
  expect(Number(await left.inputValue())).toBeCloseTo(x1, 1)
  expect(Number(await top.inputValue())).toBeCloseTo(y1, 1)
  await content.fill('SALES TEAM')
  await editor.getByRole('button', { name: 'ボックスを追加' }).click()
  await content.fill('2026')
  await save.click()
  await expect(editor).toHaveCount(0)

  const messages: string[] = []
  page.on('dialog', async dialog => {
    messages.push(dialog.message())
    await dialog.accept()
  })
  await parent.getByRole('button', { name: 'マスタから削除' }).click()
  await expect.poll(() => messages.join('\n')).toContain('営業用')
  await expect(parent).toBeVisible()
  await expect(child).toBeVisible()
  await child.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'PDF 作成（1件）' }).click()
  await page.getByRole('button', { name: '作成', exact: true }).click()
  await expect(page.locator('#pdf-msg')).toContainText('作成しました')
  const [sheet] = await (await page.request.get('/api/sheets')).json()
  const pdf = await page.request.get('/files/' + sheet.pdf_path)
  expect(pdf.ok()).toBeTruthy()
  expect((await pdf.body()).subarray(0, 5).toString()).toBe('%PDF-')
})

test('TEXT-02 スマートフォン幅で文字を編集できる', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await masterTab(page).click()
  await cardNamed(page, 'Alpha').getByRole('button', { name: '文字入りマスタを作成' }).click()
  const editor = page.getByRole('dialog')
  await editor.getByLabel('文字', { exact: true }).fill('SALES')
  await expect(editor.locator('.text-stage .text-ink')).toBeVisible()
  expect(await editor.evaluate(el => el.scrollWidth)).toBeLessThanOrEqual(
    await editor.evaluate(el => el.clientWidth + 1),
  )
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editor).toHaveCount(0)
})
