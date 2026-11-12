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
`--home` / `--config` はサブコマンドの前後どちらに置いてもよい（両方に書いたら後ろが優先）。
`ingest` / `serve` の初回実行時に `inbox/` `processed/` `jobs/` `db.sqlite3` が作られる。

## 使い方

| コマンド | 内容 |
|---|---|
| `print-edit detect <image> --out <dir> [--dpi N]` | 検出と切り出し。`cards/NN.png` と `detect.json` |
| `print-edit impose <card.png>... --out <pdf>` | 面付け PDF と `<pdf>.layout.json` |
| `print-edit capacity` | 現在の設定での容量 |
| `print-edit ingest` | inbox を1回走査して処理し終了。error ジョブが1件でもあれば終了コード 1 |
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
home は plist の環境変数 `PRINT_EDIT_HOME` で決まる（`--home` は使わない）。

1. ひな形をコピーし、`__USER__` `__PROJECT_DIR__`（このリポジトリの絶対パス）`__UV_PATH__`（`which uv` の結果。例 `/Users/<you>/.local/bin/uv`）を置き換えて `~/Library/LaunchAgents/com.print-edit.ingest.plist` に置く
2. 書式確認: `plutil -lint ~/Library/LaunchAgents/com.print-edit.ingest.plist` → `OK`
3. inbox を先に作っておく: `mkdir -p ~/PrintEdit/inbox`（WatchPaths とログの置き場所）。無いまま登録しても `bootstrap` は成功するが、inbox ができるまで一度も起動しない（2026-11-12 実測: runs = 0、home も作られない。inbox を作って画像を置くと約5秒で処理された）
   `__UV_PATH__ run ...` の代わりに `ProgramArguments` を `<リポジトリ>/.venv/bin/print-edit` と `ingest` の2要素にしても動く（同日実測: 画像を置いて約7秒で ok）
4. 登録: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.print-edit.ingest.plist`（出力なし・終了コード 0 が正常）
5. 状態確認: `launchctl print gui/$(id -u)/com.print-edit.ingest | grep -E 'state|runs|last exit code'`
   登録直後に1回起動して空振りする（`runs = 1`、`ingest.out.log` に `[]`）。異常ではない
6. inbox にファイルを置き、`~/PrintEdit/jobs/` にジョブができることを確認（下の「手動確認の方法」4 節）
7. 解除: `launchctl bootout gui/$(id -u)/com.print-edit.ingest`。その後 `launchctl print gui/$(id -u)/com.print-edit.ingest` が `Could not find service` で失敗すれば解除済み
8. 登録をやめるときは plist も `~/Library/LaunchAgents/` から外す（残すとログイン時に再登録される）

ログ: `~/PrintEdit/ingest.out.log`（処理結果の JSON 配列。起動1回につき1配列）、`~/PrintEdit/ingest.err.log`（エラー・skip 理由）。

書き込み途中のファイル: `ingest` は `intake.stable_wait_s`（既定 1.0 秒）の間サイズが変わらなくなるまで同じ実行内で待ち、`intake.max_wait_s`（既定 30 秒）を超えたら今回は処理しない（stderr に理由、次回起動で処理）。
書き込み側が `stable_wait_s` より長く止まると、途中までの画像を完成品とみなして処理してしまう（下の 4-3）。

## 手動確認の方法

期待結果の出どころを各項目に付ける。

- 実測: 2026-11-12 にこの Mac（Apple Silicon・macOS 26）で1回実行した値（n=1）
- 前回確認: 2026-11-11 のセッションで確認した値
- 未実施: 実機・実物が無く実行していない。期待値は仕様からの推定

試すときは毎回新しい home を使う（例 `sandbox/manual_1`、`sandbox/manual_2` …。`sandbox/` は git 管理外）。
`~/PrintEdit` を指定しない限り、本番の inbox・DB には触れない。

### 0. 準備（初回だけ）

```
uv sync
uv run python tests/acceptance/make_fixtures.py   # tests/acceptance/fixtures/images/ に 32 枚、約 57 MB
```

確かめるのに便利なテスト画像（`tests/acceptance/fixtures/images/`）。期待値は 600 dpi・既定設定での実測。

| ファイル | 内容 | 期待結果（実測） |
|---|---|---|
| `a3_three_col.png` | 名刺3枚（傾き −4°・0°・7°） | ジョブ ok、カード3枚 ok、各 91.02〜91.03 × 55.03 mm、シート1枚 |
| `a1_deg_p15.png` | 名刺1枚（15° 傾き） | ok、91.04 × 55.04 mm、角度 15.0° |
| `a5_wrong_size_15.png` | 名刺より小さい札（89 × 51 mm） | review、理由 `size_out_of_tolerance`、89.04 × 51.04 mm、シート0枚 |
| `a6_meta300.png` | 解像度情報が 300 dpi | review、理由 `size_out_of_tolerance` と `dpi_mismatch`（182.07 × 110.07 mm と2倍に測られる） |
| `a5_zero_noise.png` | カードなし（ノイズのみ） | review、カード0枚 |
| `a11_a4_full.png` | A4 全面 600 dpi（19 MB） | ok、カード1枚。処理時間 約1秒（前回確認 1.03 秒・最大 0.73 GB） |

上の5枚（a11 以外）を1回の `ingest` に入れたときの所要時間: 2.59 秒（実測、`uv` 起動込み）。

### 1. コマンドだけで1周する（紙は出ない）

```
mkdir -p sandbox/manual_1/inbox
cp tests/acceptance/fixtures/images/a3_three_col.png sandbox/manual_1/inbox/
uv run print-edit ingest --home sandbox/manual_1
```

期待結果（実測）

- 標準出力に `[{"job_id": "<日時>-<6桁>", "status": "ok", "cards": 3, "sheets": 1}]`、終了コード 0
- `sandbox/manual_1/inbox/` が空になり、`processed/<job_id>_a3_three_col.png` に移る
- `jobs/<job_id>/` に `source.png`・`detect.json`・`cards/01.png〜03.png`・`sheets/01.pdf`・`sheets/01.layout.json`
- `cards/01.png` は 2150 × 1299 px・600 dpi（`sips -g pixelWidth -g pixelHeight -g dpiWidth <png>` で確認）
- `sheets/01.pdf` は A4 1ページ（MediaBox 595.28 × 841.89 pt = 210 × 297 mm）。プレビュー.app で開くと、左上から右へ2枚、2段目左に1枚
- `sheets/01.layout.json` の slots は (x, y, w, h) = (14, 11, 91, 55)・(105, 11, 91, 55)・(14, 66, 91, 55) mm。容量は10枚（2列 × 5行、`uv run print-edit capacity --home sandbox/manual_1` で確認）
- 同じファイルをもう一度 inbox に入れると、ジョブは作られず `processed/` へ移るだけ（重複判定。出力 `[]`）

### 2. 管理画面で確かめる

```
uv run print-edit serve --home sandbox/manual_2 --port 8765
```

ブラウザで http://127.0.0.1:8765/ を開く。止めるときはターミナルで Ctrl+C。
上部にタブ「履歴」「要確認」「設定」「面付けプレビュー」と、ボタン「今すぐ取り込み」がある。

| # | 操作 | 期待結果 | 出どころ |
|---|---|---|---|
| 2-1 | 「設定」タブを開く | 「iPrint&Scan 側で合わせる値」に 保存先 `<home>/inbox`・形式 PNG・解像度 600 dpi | 実測（API `/api/info`） |
| 2-2 | `a3_three_col.png`・`a5_wrong_size_15.png`・`a5_wrong_size_0.png` を `sandbox/manual_2/inbox/` にコピーし「今すぐ取り込み」 | 「3 件処理しました」。ジョブ ok（カード3・シート1）1件と review（カード1・シート0）2件 | 実測（API `/api/ingest`） |
| 2-3 | 「履歴」タブ | 3ジョブが並ぶ。行ごとに dpi・カード数・シート数。「原画像」「詳細」で原画像と切り出し結果を見比べられる | 前回確認 |
| 2-4 | 「要確認」タブ | カードが2枚。89.04 × 51.04 mm（傾き 15°、wrong_size_15）と 88.99 × 50.97 mm（傾き 0°、wrong_size_0）。各カードに「承認」「180度回転」「破棄」 | 実測（カード）／前回確認（ボタン） |
| 2-5 | 89.04 × 51.04 mm のカードで「承認」 | カードが printed になり、シートが1枚追加される（per_scan のため1枚だけのシート）。要確認は残り1枚 | 実測（API approve） |
| 2-6 | 残りのカードで「180度回転」 | 切り出し画像が上下逆になり（画像ファイルの内容が変わる）、カードは要確認に残る | 実測（API rotate）／上下逆は前回確認 |
| 2-7 | 同じカードで「破棄」 | カードが discarded になり要確認から消える。印刷されない。要確認は「要確認のカードはありません」 | 実測（API discard） |
| 2-8 | 「面付けプレビュー」タブ | 「容量 10 枚（2 列 × 5 行、…）」とスロット図 | 前回確認 |
| 2-9 | 設定値（例 `layout.gap_x_mm` を 2）を変えて「保存」 | 「保存しました」。サーバを再起動しても値が残る。容量は 2 列 × 5 行・10 枚のまま（182 + 2 = 184 mm ≤ 印字可能幅 201.6 mm） | 前回確認（保存・保持）／実測（容量） |
| 2-10 | 「履歴」の「再印刷」 | 「再送しました」。保存済みの PDF をそのまま出口へ再送する（設定を変えていても PDF は作り直されない。`print.output=pdf` なら紙は出ない） | 実測（API reprint、PDF のハッシュ不変） |
| 2-11 | 取込の最中に「今すぐ取り込み」を押す | 「0 件処理しました」（ほかの取込がロック中。取りこぼしは無く、次回に処理される） | 前回確認（既知の軽微事項） |

確認後の状態は `sqlite3 sandbox/manual_2/db.sqlite3 "select source_name,status from jobs"` でも見られる。

### 3. 印刷して定規で測る（紙が出る・未実施）

実機到着後に行う。ここだけは実際に紙が出る。

1. `lpstat -p` でプリンタのキュー名を確認する（例 `Brother_DCP_L2600DW`。実際の名前は未確認）
2. `lpoptions -p <キュー名> -l` で用紙・トレイ・倍率の選択肢を確認し、等倍（拡大縮小なし）・A4 を指定する `-o` を決める
3. 新しい home で設定する。管理画面の「設定」か `<home>/config.json` で次を入れる
   - `print.output`: `lp`
   - `print.printer_name`: 手順1のキュー名（空のままだと印刷前にエラーになる。既定プリンタへの誤印刷を防ぐため）
   - `print.lp_options`: 手順2で決めた値。1要素ごとに `-o` が付く（`-o` は書かない）。例 `["media=A4"]`（偽 lp で `-o media=A4` になることを前回確認）。等倍の指定は `lpoptions -l` の出力から選ぶ（オプション名は未確認）
4. `a3_three_col.png` を inbox に入れて取り込む → A4 が1枚出る
5. 定規（できれば 0.5 mm 目盛り）で測る。期待値は `sheets/01.layout.json` の値
   - トンボ（長さ 3 mm・太さ 0.1 mm・黒）は、カードの角から 1 mm 外側に出ている
   - 縦トンボの間隔: 左端 x=14 → 中央 x=105 → 右端 x=196 mm。間隔はどちらも 91.0 mm
   - 横トンボの間隔: y=11 → 66 → 121 mm。間隔はどちらも 55.0 mm
   - 用紙左端からトンボまで 14 mm、上端から 11 mm（印字の位置ずれの目安）
6. ずれていたら補正する（用紙中心基準で全体に掛かる）
   - `print.scale_x` の新しい値 = 今の値 × 91.0 ÷ 実測した横の間隔（例: 実測 90.5 mm なら 1.0 × 91.0 ÷ 90.5 ≈ 1.0055）
   - `print.scale_y` の新しい値 = 今の値 × 55.0 ÷ 実測した縦の間隔
   - 設定できる範囲は 0.95〜1.05
7. 余白側が欠けるときは `device.unprintable_mm`（既定 4.2）を実測値に合わせる
8. トンボが濃すぎる・薄すぎるときは `layout.mark_gray`（0=黒〜255=白）、`layout.mark_width_mm` で調整する
9. 測り直すときは、設定を直した config.json を新しい home にコピーし、同じ画像をその inbox に入れて取り込み直す。「再印刷」（2-10）は保存済みの PDF を再送するだけなので補正が反映されない。同じ home に同じ画像を入れても重複扱いでジョブは作られない

### 4. launchd で自動取込を確かめる

先に上の「launchd 登録手順」で登録する。次の数値は、ひな形から Label を `com.print-edit.ingest.test`、home を `sandbox/launchd_1` に変えた一時登録での実測（各1回、`print.output=pdf`）。

| # | 操作 | 期待結果（実測） |
|---|---|---|
| 4-1 | `a3_three_col.png` を inbox にコピー | 1.67 秒でジョブの行ができ、1.88 秒で inbox が空になる。ok・カード3枚。`runs` が 1 増える |
| 4-2 | 2枚を続けてコピー（`a3_three_row.png`・`a1_deg_p15.png`） | 1回の起動で2件とも処理される（`runs` +1、出力は2要素の配列1つ）。2.37 秒で2件とも ok |
| 4-3 | 同じファイル名に前半を書き、3秒止めてから後半を書く | 前半だけの時点で処理され、error `image file is truncated`（この実行の終了コードは 1）。ファイルは書き込み中のまま `processed/` に移る（後半はそちらに書かれ、全長 266,803 バイトになった）。起動は2回（2回目は `[]` で終了コード 0。`last exit code` にはこちらが残る） |
| 4-4 | 19 MB の `a11_a4_full.png` の処理中に `a1_deg_m30.png` を追加 | 処理中の起動では拾われず、終了後の再起動で処理される（`runs` +2、出力は1要素の配列が2つ）。2件とも ok。2件目のジョブは1件目の約6秒後にできる（再起動は前回の起動から5秒空ける `ThrottleInterval 5` のため）。2件そろうまで 6.89 秒 |

4-3 の復旧と回避

- 復旧（実測）: `processed/<job_id>_<元の名前>` のサイズが元ファイル（スキャンし直すならその結果）と同じことを確かめてから、別名で inbox にコピーし直す → ok・カード3枚。error ジョブのハッシュは途中までの内容なので重複扱いにはならない。今回は書き込み側が同じファイルを開いたままだったので後半が processed 側に入り全長になったが、書き込み方によっては途中までのままになる。その場合はスキャンし直す
- 回避（実測、launchd なし）: `intake.stable_wait_s` を書き込み側の止まる時間より長くする。3秒止まる書き込みで 1.0 秒 → error、5.0 秒 → ok（11.0 秒）。代わりに1件ごとの待ちが長くなる
- iPrint&Scan が実際にどう書き込むか（一時名からのリネームか、直接書きか、途中で止まるか）は未確認。実機到着後に確かめる

### 5. 実物の名刺を試す（未実施）

1. 名刺3枚程度を黒い紙（または蓋を開けた状態）の上に、互いに 1 cm 以上離して置く
2. iPrint&Scan で 600 dpi・PNG・保存先を inbox にしてスキャンする
3. 期待結果（推定）: カードごとに ok、寸法は 91 ± 1.5 mm × 55 ± 1.5 mm（`detect.size_tolerance_mm`）に入る。外れたカードは要確認に回る
4. うまく切れないとき
   - カードが検出されない: 背景が明るい。暗い背景にする。`detect.threshold` を指定する（既定は自動）
   - 2枚が1枚として検出される: カード同士が近すぎる
   - 灰色の地が残る: `correct.whiten_level`（既定 200）を下げる。文字が薄くなるときは上げる
   - 全カードが要確認・理由 `dpi_mismatch`: スキャン解像度と `intake.expected_dpi` が違う

### 6. スマホで撮った写真を試す（未実施）

`cp <写真>.jpg sandbox/manual_3/inbox/` → `uv run print-edit ingest --home sandbox/manual_3`。
期待結果（推定）: 写真には正しい dpi 情報が無く、寸法が名刺サイズにならないため、カードは要確認（`size_out_of_tolerance` など）になる見込み。
今はスマホ撮影に対応していない（将来のスマホアプリ展開で扱う）。

### 7. 自動テスト

```
uv run pytest tests -q
```

期待結果（実測、2026-11-12）: 175 passed, 1 skipped（約3分）。内訳は単体 47、受け入れ 107 + skip 1、追加受け入れ 21。
skip の1件は「印刷先が空のとき lp を実行しない」テストで、この Mac に実在のプリンタが登録されていると誤印刷を避けるため skip になる。プリンタ未登録の Mac では 0 skipped になる見込み（推定）。

### 8. うまくいかないとき

| 症状 | 見る場所・コマンド |
|---|---|
| ジョブができない | `ls <home>/inbox`（残っていれば未処理）。`uv run print-edit ingest --home <home>` を手で実行して標準出力・標準エラーを見る |
| `[]` しか出ない | ほかの ingest が実行中（`<home>/ingest.lock` を握っている）か、同じ内容のファイルを処理済み（重複）。`pgrep -fl "print-edit ingest"` |
| launchd で動かない | `launchctl print gui/$(id -u)/com.print-edit.ingest` の `last exit code`、`<home>/ingest.err.log`、plist の `uv` の絶対パス。`uv run` で起動しないときは `ProgramArguments` を `<リポジトリ>/.venv/bin/print-edit` と `ingest` の2要素に替える（この代替は未検証） |
| 要確認ばかりになる | 管理画面「要確認」の理由。`dpi_mismatch` → 解像度設定、`size_out_of_tolerance` → 寸法（`jobs/<id>/detect.json` の `long_mm` / `short_mm`） |
| error ジョブ | `sqlite3 <home>/db.sqlite3 "select id,source_name,error from jobs where status='error'"`。`image file is truncated` は 4-3 |
| 印刷されない | `lpstat -o`（キュー）、`print.printer_name`、`print.output`。シートの状態は `select id,status,error from sheets` |
| 管理画面が開かない | `lsof -i tcp:8765` でポートが使われていないか。`--port` を変える |

## 実機到着後に確認する項目

- 実際のスキャン画像（解像度情報・背景色・影）で検出が通るか（`detect` の結果と `jobs/<id>/cards/`）
- `device.unprintable_mm`（既定 4.2）の実測値。余白が合わないときは調整
- `print.scale_x` / `scale_y`（0.95〜1.05）で実寸のずれを補正（手動確認 3 節）
- `print.printer_name`（`lpstat -p` のキュー名）、`print.lp_options`（用紙・両面などの `-o`）。設定後、`print.output` を `lp` にする
- モノクロ機の濃度: `correct.whiten_level`、トンボ濃度 `layout.mark_gray`
- トンボ位置が裁断に使えるか、カード寸法・許容差 `detect.size_tolerance_mm`
- iPrint&Scan の保存形式・解像度・保存先が上記設定どおりか
- iPrint&Scan の書き込み方（一時名からのリネームか直接書きか、途中で止まる時間）。止まるなら `intake.stable_wait_s` を延ばす（手動確認 4-3）
- lp は実機到着まで実行していない。`printer_name` が空だと実行前にエラーになる（既定プリンタへの誤印刷防止）
- 用紙の種類・厚さ（斤量）・手差し・給紙トレイ: アプリに専用の設定は無い。`lpoptions -p <キュー名> -l` で機種が受け付ける項目名と値（例 `MediaType`・`InputSlot`）を確かめ、`print.lp_options` に書く。専用の設定にするかは、その結果を見てから決める（実機待ち）
- macOS の「バックグラウンド項目が追加されました」通知が launchd 登録時に出るか（画面の通知なので手で確認）

## 構成

`src/print_edit/` : `core/`（設定・検出・面付け・PDF）→ `adapters/`（入口 folder、出口 pdf_file / lp）→ `store/`（SQLite）→ `pipeline.py` → `api/` `web/` `cli.py`。
