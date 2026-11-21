import { test as setup } from '@playwright/test'
import * as fs from 'fs'

import { authFile, HOST_ROLES } from '../wt'

// print-edit はログイン無しのアプリ（bt_config.md「認証に関する注記」）。
// playwright.config の tests プロジェクトが setup に依存するため、何もしない setup を1件置く。
setup('authenticate: none（ログイン無し）', async () => {})

// accounts/<host>.local にロールを足した場合だけ回る（通常は0件）。ログイン画面が無いので空の storageState を書く
for (const role of HOST_ROLES) {
  setup(`authenticate: ${role}`, async () => {
    const statePath = authFile(role)
    fs.rmSync(statePath, { force: true })
    fs.mkdirSync(require('path').dirname(statePath), { recursive: true })
    fs.writeFileSync(statePath, JSON.stringify({ cookies: [], origins: [] }))
  })
}
