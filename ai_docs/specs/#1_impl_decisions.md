# #1 実装判断ログ（/im 2026-11-20）

正本 `#1_main.md` は凍結（main.md と cmp 同一）のため、/im Step 5 の「実装判断ログ」はここに置く（/im からの逸脱。advisor 指摘 #8）。main へ取り込むときに /st が main.md の「実装判断ログ」へ移す。

## implementer（sonnet）が正本に無く決めたこと
- U-5: alert「…失敗: <detail>」の detail はサーバ応答の `detail` をそのまま。配列なら `loc: msg` を " / " で連結
- U-15: PDF 作成画面の新規保存 = `POST /api/pdf`（{items[{card_id,count}], slots?, preset} → {sheets[{id,status}], delivery{ok,error}}）。上書き = `PUT /api/sheets/{id}/pdf`（送信中 409・作成結果2件以上 422）
- U-16: 一括登録・一括破棄の失敗行 = `失敗 #<id> <source_name>: <detail>`（results 要素 {id, ok, source_name, idx, detail}）。シートの一括印刷・一括破棄 = `成功/失敗 #<sheet_id> <detail>`
- J24（未回答）: 印刷待ち0件では一括操作バーを出さない（A）を仮置き。src/print_edit/web/app.js:314 の `if (sheets.length)` 1箇所
- 取込&作成は review カードを PDF に含めない（M22・N-76）
- DB 移行: 旧 ok/printed/held/pending/review → reg=pending・migrated=1、discarded → reg=discarded。`BEGIN IMMEDIATE`・`db.sqlite3.bak` 作成・冪等
- 旧 config.json（layout・timing=fill・duplicate_count）は読み込み時に自動移行。組み込み既定値「既定」へ cards_per_sheet を引き継ぎ、auto_ingest=ingest_create。`.bak` 作成・冪等
- 外部 --config（Home に config を明示）は読み取り専用。旧形式でもメモリ上で全体設定＋既定値へ変換して「既定」より優先し、ファイル・.bak・DB は書かない（X-09）。serve --config 時の API 保存（api/app.py:132,533）による外部ファイル上書きは範囲外の残り
- 取込タブ「取り込みのみ」ボタン・取込&作成ダイアログのラベル構造（全体設定「使う既定値」の select は radio と別 label）
- `GET /api/capacity` を旧テストのため維持
- 互換用に home.load_settings（全体＋既定値の合成）・save_settings を残した
- モックの取込&作成ダイアログ「対象: 未取り込みの画像 n 件」は件数 API が無く未実装（正本に記述なし）

## 移行後のスキーマ・キー（test-data 用）
- cards: 既存列 ＋ reg（pending/master/deleted/discarded）・name・migrated
- sheets: 既存列 ＋ snapshot
- presets（新規）: id, name, data, builtin, created_at
- jobs・sheet_cards: 変更なし
- config.json: auto_ingest(mode: ingest_only|ingest_create, preset_id)・last_preset_id・intake・detect・print・device。補正・面付けは presets.data(correct, layout, arrange)

## ルート一覧（追加・変更）
GET/PUT /api/config・GET /api/config/schema・GET/POST /api/presets・GET /api/presets/schema・PUT/DELETE /api/presets/{id}（builtin・自動取込参照中は 409）・GET/POST /api/layout/preview・GET /api/capacity・GET /api/cards（status・reg・q）・POST /api/cards/{id}/register・POST /api/cards/{id}/discard・DELETE /api/cards/{id}・POST /api/cards/{id}/rotate・PUT /api/cards/{id}/name・POST /api/bulk/cards/register・POST /api/bulk/cards/discard・GET /api/history・GET /api/sheets・GET /api/sheets/{id}/image.png・GET /api/sheets/{id}/adjust・POST /api/sheets/{id}/print・POST /api/sheets/{id}/reprint・POST /api/sheets/{id}/discard・POST /api/bulk/sheets/print・POST /api/bulk/sheets/discard・POST /api/pdf・PUT /api/sheets/{id}/pdf・POST /api/ingest（取り込みのみ）・POST /api/ingest/create
廃止（404）: POST /api/cards/{id}/approve・POST /api/jobs/{id}/reprint
