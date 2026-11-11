# print-edit

名刺サイズの原稿のスキャン画像を、カードごとに切り出し・傾き補正し、A4 に面付けした PDF にして印刷へ送る Mac 用ツール。
仕様の正本は `docs/spec.md`。実機（ブラザー DCP-L2600DW）未着のため、実機依存の値はすべて設定値。

## 導入

```
uv sync
uv run print-edit config show      # 既定設定の確認
uv run print-edit config path      # 設定ファイルの場所（既定 ~/PrintEdit/config.json）
```

データ置き場は `PRINT_EDIT_HOME`（未設定時 `~/PrintEdit`）。`--home <dir>` で上書きできる（試すときは一時フォルダを指定する）。
`ingest` / `serve` の初回実行時に `inbox/` `processed/` `jobs/` が作られる。

## 使い方

| コマンド | 内容 |
|---|---|
| `print-edit detect <image> --out <dir> [--dpi N]` | 検出と切り出し。`cards/NN.png` と `detect.json` |
| `print-edit impose <card.png>... --out <pdf>` | 面付け PDF と `<pdf>.layout.json` |
| `print-edit capacity` | 現在の設定での容量 |
| `print-edit ingest` | inbox を1回走査して処理し終了 |
| `print-edit serve [--port 8765]` | 管理画面と API（127.0.0.1 のみ）。ブラウザで `http://127.0.0.1:8765/` |
| `print-edit config show\|schema\|path` | 設定の表示・JSON Schema・パス |

テスト: `uv run pytest tests/unit -q`

受け入れテスト: テスト画像（約 57 MB、git 管理外）を生成してから実行する。生成は固定シードで、何度実行しても同じ画像になる。

```
uv run python tests/acceptance/make_fixtures.py
uv run pytest tests/acceptance -q
```

## iPrint&Scan 側で合わせる設定

管理画面の「設定」にも同じ内容が出る。

- 保存先: inbox（既定 `~/PrintEdit/inbox`、設定 `intake.inbox_dir` で変更可）
- 形式: PNG（JPEG / TIFF / PDF も取り込めるが PNG を推奨）
- 解像度: 600 dpi（`intake.expected_dpi` と一致させる。画像に解像度情報があればそちらを使い、不一致ならカードは要確認になる）
- 原稿は暗い背景（蓋を開ける、黒い台紙など）に置き、カード同士を接触させない

## launchd 登録手順（自動取込）

`deploy/com.print-edit.ingest.plist` はひな形。登録は手動で行う（このツールは自動登録しない）。

1. `__USER__` `__PROJECT_DIR__` `__UV_PATH__`（`which uv`）を置き換えて `~/Library/LaunchAgents/com.print-edit.ingest.plist` に置く
2. `launchctl load ~/Library/LaunchAgents/com.print-edit.ingest.plist`
3. inbox にファイルを置き、`~/PrintEdit/jobs/` にジョブができることを確認
4. 解除: `launchctl unload ~/Library/LaunchAgents/com.print-edit.ingest.plist`

WatchPaths は書き込み途中でも発火するが、`ingest` が `intake.stable_wait_s` の間サイズが変わるファイルを処理対象から外す（次回起動で処理）。

## 実機到着後に確認する項目

- 実際のスキャン画像（解像度情報・背景色・影）で検出が通るか（`detect` の結果と `jobs/<id>/cards/`）
- `device.unprintable_mm`（既定 4.2）の実測値。余白が合わないときは調整
- `print.scale_x` / `scale_y`（0.95〜1.05）で実寸のずれを補正
- `print.printer_name`（`lpstat -p` のキュー名）、`print.lp_options`（用紙・両面などの `-o`）。設定後、`print.output` を `lp` にする
- モノクロ機の濃度: `correct.whiten_level`、トンボ濃度 `layout.mark_gray`
- トンボ位置が裁断に使えるか、カード寸法・許容差 `detect.size_tolerance_mm`
- iPrint&Scan の保存形式・解像度・保存先が上記設定どおりか
- lp は実機到着まで実行していない。`printer_name` が空だと実行前にエラーになる（既定プリンタへの誤印刷防止）

## 構成

`src/print_edit/` : `core/`（設定・検出・面付け・PDF）→ `adapters/`（入口 folder、出口 pdf_file / lp）→ `store/`（SQLite）→ `pipeline.py` → `api/` `web/` `cli.py`。
