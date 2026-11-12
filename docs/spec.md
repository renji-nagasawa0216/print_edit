# print-edit 仕様（正本）

名刺サイズの原稿を複合機（ブラザー DCP-L2600DW、モノクロ）でスキャンした画像を受け取り、
カードごとに切り出し・傾き補正し、用紙に面付けした PDF を作って印刷へ送る Mac 用ツール。
実機は未着。実機でしか決まらない値はすべて設定値にする。

用語
- カード: 原稿1枚（既定 91 × 55 mm）
- ジョブ: 取り込んだスキャン画像1ファイル分の処理単位
- シート: 面付け後の用紙1枚
- 要確認(review): 自動印刷に進めず人の確認を待つ状態

## 1. 構成と依存の向き

Python 3.12、uv 管理、パッケージ `src/print_edit/`。

| 層 | パス | 役割 | 依存してよいもの |
|---|---|---|---|
| core | `core/` | 検出・補正・面付け計算・PDF 生成・設定の型 | numpy / opencv / pillow / reportlab / pydantic のみ。ファイル監視・DB・HTTP・subprocess を import しない |
| adapters | `adapters/` | 入口（`sources/folder.py`）、出口（`printers/pdf_file.py`, `printers/lp.py`） | core |
| store | `store/` | SQLite と画像ファイルの保存 | core の型 |
| pipeline | `pipeline.py` | 取込 → 検出 → 保存 → 面付け → 出力 の進行 | 上記すべて |
| api | `api/` | FastAPI | pipeline, store |
| web | `web/` | 管理画面（ビルド不要の HTML + JS。API だけを呼ぶ） | なし |
| cli | `cli.py` | コマンド `print-edit` | 上記すべて |

入口・出口は Protocol（抽象）を定義し、設定値で実装を選ぶ。将来の入口（eSCL、アップロード）追加で core と pipeline を変更しないこと。

## 2. データ置き場

環境変数 `PRINT_EDIT_HOME`（未設定時 `~/PrintEdit`）を根とする。テストは必ず一時フォルダを指定する。

```
$PRINT_EDIT_HOME/
  config.json        設定（無ければ既定値）
  inbox/             監視フォルダ（設定 intake.inbox_dir が空のときの既定）
  processed/         処理済みの元ファイル（消さずに移動）
  jobs/<job_id>/     source.png, cards/NN.png, sheets/NN.pdf, sheets/NN.layout.json, detect.json
  db.sqlite3
  ingest.lock
```

## 3. 設定

`core/settings.py` の pydantic モデルを唯一の正とする。長さは mm。既定値・検査・JSON Schema・API・画面のフォームはこのモデルから導く（画面にフォーム項目を手書きしない）。

| 節 | キー | 型 | 既定 | 内容 |
|---|---|---|---|---|
| intake | inbox_dir | str | "" | 空なら `$PRINT_EDIT_HOME/inbox` |
| intake | extensions | list[str] | png,jpg,jpeg,tif,tiff,pdf | 大文字小文字を区別しない |
| intake | expected_dpi | int | 600 | 画像に解像度情報が無いときに使う値。あるときは画像の値を使い、不一致なら警告 |
| intake | stable_wait_s | float | 1.0 | この秒数サイズが変わらなければ書き込み完了とみなす |
| intake | max_wait_s | float | 30 | 書き込み完了待ちの上限（同じ実行内で待つ） |
| detect | card_width_mm / card_height_mm | float | 91 / 55 | 長辺 / 短辺 |
| detect | size_tolerance_mm | float | 1.5 | 検出寸法の許容差（各辺） |
| detect | min_area_ratio | float | 0.25 | カード面積に対しこの比未満の明領域は無視 |
| detect | threshold | int or null | null | 2値化の閾値（0-255）。null は自動（大津） |
| correct | size_mode | "fit" / "actual" | fit | fit: カード寸法へ伸縮。actual: 実寸のままカード寸法の白地中央に置く |
| correct | rotate_180 | bool | false | 全カードを 180 度回す |
| correct | whiten_level | int | 200 | 出力時、紙の明るさ（照明むら）で正規化した輝度がこの値以上の画素を白にする。それ未満は元の値のまま（0 で無効） |
| layout | paper_width_mm / paper_height_mm | float | 210 / 297 | |
| layout | cards_per_sheet | int or null | null | null は上限。上限超は検査エラー |
| layout | gap_x_mm / gap_y_mm | float | 0 / 0 | |
| layout | mark_enabled / mark_length_mm / mark_width_mm / mark_gray / mark_offset_mm | bool/float/float/int/float | true / 3 / 0.1 / 0 / 1 | トンボ。gray は 0=黒〜255=白 |
| layout | mark_style / mark_dash_mm / mark_gap_mm | "solid" / "dashed", float, float | solid / 1 / 1 | トンボの線種。dashed のとき実線部 dash_mm・空白部 gap_mm の破線（dash・gap は 0 より大きい）。11.2 参照 |
| print | output | "pdf" / "lp" | pdf | |
| print | timing | "per_scan" / "fill" / "duplicate" | per_scan | 5.3 参照 |
| print | printer_name | str | "" | lp のキュー名 |
| print | lp_options | list[str] | [] | `-o` に渡す文字列 |
| print | copies | int | 1 | |
| print | duplicate_count | int or null | null | timing=duplicate のとき名刺1枚あたりに並べる面数。null は従来どおり枠を埋める。1 以上。1 シートの枚数を超えたら検査エラー。11.5 参照 |
| print | color_mode | "mono" / "color" | mono | 機種が color 非対応なら検査エラー |
| print | scale_x / scale_y | float | 1.0 / 1.0 | 用紙中心を基準にした補正係数（0.95〜1.05） |
| device | unprintable_mm | float | 4.2 | 四辺 |
| device | supports_color | bool | false | |

## 4. 検出・補正（core）

入力: 画像（カード = 明、背景 = 暗）。出力: カードごとの幾何情報と補正済み画像。

1. 解像度を決める（画像の情報 → 無ければ expected_dpi）
2. グレー化 → 平滑化 → 2値化 → 明領域の輪郭抽出
3. 面積が `min_area_ratio × カード面積` 未満の領域は捨てる
4. 各領域に最小外接長方形を当て、四隅・中心・長辺/短辺(mm)・傾きを得る
5. 長辺・短辺のどちらかがカード寸法 ± size_tolerance_mm を外れたら review（理由 `size_out_of_tolerance`）
6. 四隅から射影変換で切り出す。出力は必ず横長（長辺が水平）。画素数は fit のとき `round(card_mm / 25.4 * dpi)`
7. 出力順は中心座標の上 → 下、同じ行なら左 → 右
8. 切り出し画像は色を保ったまま保存する。グレー化と白飛ばしは PDF 生成時に行う

カード 0 件はジョブを review（理由 `no_cards`）。解像度不一致はジョブに警告 `dpi_mismatch` を付け、カードは review にする。

上下逆（180 度）は判定しない。

## 5. 面付け（core）

### 5.1 容量
印字可能域 = 用紙 − 2 × unprintable_mm。カードを横置き・縦置き（90 度回転）の両方で
`floor((可能域 + gap) / (カード辺 + gap))` を縦横に計算し、枚数が多い方を採る（同数なら横置き）。
既定値では 2 列 × 5 行 = 10。

### 5.2 配置
格子全体を印字可能域の中央に置く。スロットは上の行から、行内は左から埋める。
トンボは各裁断線の延長上、格子の外側に `mark_offset_mm` 離して `mark_length_mm` だけ引く。印字可能域からはみ出す部分は描かない。
scale_x / scale_y は用紙中心基準で全要素に掛ける。
PDF のページ寸法は用紙寸法と一致させる（1 pt = 25.4/72 mm）。

### 5.3 タイミング
- per_scan: そのジョブの ok カードだけでシートを作る（容量を超えたら複数シート）
- fill: ok カードを保留に積み、cards_per_sheet 枚たまるごとに1シート作る。端数は保留のまま
- duplicate: そのジョブの ok カードを順に繰り返して cards_per_sheet 枠を埋める（`print.duplicate_count` を指定したときは名刺1枚あたりの面数を指定できる。11.5 参照）

review のカードはどのモードでもシートに入れない。承認されたら ok と同じ扱いでそのモードの規則に従う。

## 6. コマンド（検証の接点。出力形式を変えない）

共通: `--home <dir>` で PRINT_EDIT_HOME を上書き、`--config <json>` で設定ファイルを指定。失敗は終了コード 非 0、stderr に理由。

### `print-edit detect <image> --out <dir> [--dpi N]`
`<dir>/cards/NN.png`（01 始まり）と `<dir>/detect.json` を書き、同じ JSON を stdout に出す。

```json
{
  "source": {"path": "...", "width_px": 0, "height_px": 0, "dpi": 600, "dpi_source": "metadata|config|option"},
  "status": "ok|review",
  "warnings": ["dpi_mismatch"],
  "cards": [
    {"index": 1,
     "corners_px": [[x, y], [x, y], [x, y], [x, y]],
     "center_mm": [x, y],
     "long_mm": 91.0, "short_mm": 55.0,
     "angle_deg": 0.0,
     "status": "ok|review", "reasons": [],
     "image": "cards/01.png", "image_width_px": 2150, "image_height_px": 1299}
  ]
}
```
- corners_px は元画像上の四隅（順不同でよい）。原点は左上
- center_mm は原点左上、dpi で換算
- angle_deg は長辺と水平のなす角、範囲 (-90, 90]、画像座標で時計回りを正

### `print-edit impose <card.png>... --out <pdf>`
PDF と `<pdf>.layout.json` を書く。枚数が容量を超えたら `<pdf>` を1枚目とし `-2.pdf`, `-3.pdf` … を作る。

```json
{
  "paper_mm": [210.0, 297.0],
  "printable_mm": [x, y, w, h],
  "capacity": 10, "columns": 2, "rows": 5, "card_rotated": false,
  "slots": [{"index": 1, "x": 0, "y": 0, "w": 91, "h": 55, "card": "01.png"}],
  "marks": [{"x1": 0, "y1": 0, "x2": 0, "y2": 0}]
}
```
座標は mm、原点は用紙左上。slots は scale 適用後の実配置。

### `print-edit capacity`
現在の設定での `{"capacity","columns","rows","card_rotated"}` を stdout に JSON で出す。

### `print-edit ingest`
inbox を1回走査して終了する（launchd の WatchPaths から起動される想定）。
- `ingest.lock` を排他ロックし、取れなければ何もせず終了コード 0
- stable_wait_s の間サイズが変わらなくなるまで同じ実行内で待つ。max_wait_s を超えたファイルは今回は処理せず stderr に理由（終了コード 0）
- 内容の SHA-256 が処理済みと同じファイルは再処理せず processed/ へ移す
- 処理後、元ファイルは `processed/<job_id>_<元の名前>` へ移動（削除しない）
- 1ファイルの失敗で他のファイルの処理を止めない。失敗ジョブは status=error で記録
- stdout に処理結果の JSON 配列（job_id, status, cards, sheets）

### `print-edit serve [--port 8765]`
127.0.0.1 のみで API と管理画面を起動する。

### `print-edit config show|schema|path`

## 7. 出口

- pdf: シートの PDF を `jobs/<job_id>/sheets/` に置くだけ
- lp: `lp -d <printer_name> -n <copies> [-o opt]... <pdf>`。printer_name が空なら実行せずエラーにする（`-d` 無しの lp は既定プリンタへ実際に印刷されるため）。テストでは lp を実行しない（コマンド組み立てだけを検査）

## 8. 保存（SQLite）

- jobs: id, source_name, sha256, status(ok/review/error), warnings, dpi, created_at
- cards: id, job_id, index, status(ok/review/pending/printed/discarded), reasons, 幾何情報, image_path
- sheets: id, job_id(null 可), pdf_path, status(created/sent/error), created_at
- sheet_cards: sheet_id, card_id, slot

## 9. API（127.0.0.1 のみ、認証なし）

| メソッド | パス | 内容 |
|---|---|---|
| GET | /api/config, /api/config/schema | 設定と JSON Schema |
| PUT | /api/config | 全体を置き換え。検査エラーは 422 |
| GET | /api/capacity | 5.1 の結果 |
| GET | /api/jobs, /api/jobs/{id} | 新しい順。詳細はカード・シートを含む |
| GET | /api/cards?status= | |
| POST | /api/cards/{id}/approve, /discard, /rotate | rotate は切り出し画像を 180 度回す |
| POST | /api/jobs/{id}/reprint | シートを出口へ再送 |
| POST | /api/ingest | ingest を1回実行 |
| GET | /files/... | jobs 配下の画像・PDF（HOME の外へ出るパスは 404） |
| GET | / | 管理画面 |

## 10. 管理画面

4 画面: 履歴（原画像と切り出しの比較・再印刷）、要確認（承認・180 度回転・破棄）、設定（JSON Schema からフォーム生成、節ごとに表示）、面付けプレビュー（容量とスロット配置図）。
設定画面には「iPrint&Scan 側で合わせる値」（保存先 = inbox、形式 = PNG、解像度 = expected_dpi）を表示する。

## 11. 受け入れ基準

| # | 項目 | 基準 |
|---|---|---|
| A1 | 切り出し位置 | 傾き −45〜+45 度・600 dpi の合成画像で、四隅の誤差がそれぞれ 0.3 mm 以内 |
| A2 | 寸法 | long_mm / short_mm の誤差 0.3 mm 以内、切り出し画像は 2150 × 1299 px（600 dpi, fit） |
| A3 | 複数 | 3 枚配置で 3 件検出、順序は 4.7 のとおり |
| A4 | 耐性 | 影・照明むら・ノイズ入りでも A1 を 0.5 mm 以内で満たす |
| A5 | 異常 | 接触 2 枚・濃い縁取り・寸法違い（例 89 × 51）・0 枚 が ok にならない |
| A6 | 解像度 | 情報あり / なし / 不一致 で dpi_source と warnings が仕様どおり |
| A7 | 容量 | 既定で 10（2 × 5）。用紙・カード・隙間を変えた場合も 5.1 の式と一致 |
| A8 | 配置 | スロットが互いに重ならず、すべて印字可能域内。寸法誤差 0.01 mm 以内。PDF ページ寸法が用紙と一致（0.1 mm 以内） |
| A9 | 取込 | 同じファイルを 2 回入れても 1 ジョブ。同時に 2 プロセス起動しても壊れない。元ファイルが processed/ に残る |
| A10 | 出口 | printer_name が空の lp はエラー。テスト中に lp が実行されない |
| A11 | 時間 | 600 dpi A4 全面 1 枚の detect が 5 秒以内（目標） |

## 11.1 実装で確定した規則（2026-11-11 追記）

- カード 0 件: detect.json の最上位 `"reasons": ["no_cards"]`、status=review。平滑化後の輝度レンジが 30 未満の画像（空の原稿台）も 0 件とする
- warnings は `dpi_mismatch` と `pdf_multipage_ignored`（複数ページ PDF は 1 ページ目のみ処理）
- 使う dpi の優先順位: `--dpi` → 画像の情報 → expected_dpi。`dpi_mismatch` は画像の dpi と基準（`--dpi` があればそれ、無ければ expected_dpi）の差が 1 を超えるとき
- ジョブ status: review カードが 1 枚でもあれば review。出口（印刷）が失敗したら error（jobs.error に理由）
- ingest の終了コード: error ジョブが 1 件でもあれば非 0。ロック取得失敗は `[]` を出して 0
- 失敗したファイルも processed/ へ移す。error ジョブは SHA-256 重複判定の対象外（再投入で再処理できる）
- カードを printed にするのは出口が成功した後だけ。fill で枚数待ちのカードは pending
- impose: シート分割は cards_per_sheet（null なら容量）。slots は載せた枚数分だけ。トンボは載せたカードの外周に引き、scale 適用後の座標で印字可能域にクリップ
- 白飛ばし: 固定しきい値ではなく、カードごとに紙の明るさ（照明むら）を推定して正規化してから行う。推定はカード全体のなだらかな変化だけを拾い、局所の中間調（ベタ・帯・ロゴ）を白にしない。しきい値未満の画素は元の値のまま
- シート status: created（pdf 出力）/ sent（lp 成功）/ error（出口失敗）
- fill で複数ジョブのカードが混ざるシートが失敗した場合: 関係する全ジョブを error、カードは ok に戻す。再印刷はそのジョブのカードを含むシートを対象にし、成功時にカード printed、ジョブを再計算
- ジョブ status は approve / discard / rotate / reprint の後に再計算する（error 優先 → review → ok。discarded は判定外）
- approve の API 応答に出口の結果 `delivery: {ok, error}` を含める（fill で枚数待ちのときは ok=true）。管理画面は失敗理由を表示する
- 書き込み途中のファイル: 同じ ingest 実行内で stable_wait_s 間変化しなくなるまで待つ。上限 intake.max_wait_s（既定 30 秒）を超えたら今回は処理せず stderr に理由（終了コード 0）
- 追加 API: `GET /api/info`（inbox・dpi の表示用）、`GET /api/layout/preview`（スロット図用）。画面の静的ファイルは `/static/`

## 11.2 追記（2026-11-12）

- 再印刷: 保存済みのシート PDF をそのまま出口へ再送する。面付け・画像処理はやり直さない。取り込み後に変えた設定（scale・トンボ・用紙など）は反映されない。反映させたいときは取り込み直す。出口が pdf のときは何も送らない
- 再印刷の API 応答に、そのときの出口 `"output": "pdf" | "lp"` を含める。管理画面は output=pdf のとき「出力先が pdf のため印刷していません（PDF は保存済み）」、lp で全シート成功のとき「再送しました」を表示する
- duplicate で ok カードが cards_per_sheet を超える場合: per_scan と同じく cards_per_sheet 枚ずつに区切り、まとまりごとにその中のカードを順に繰り返して枠を埋める。カードは落とさない。例: 12 枚・容量 10 → 1 枚目はカード 1〜10、2 枚目は 11, 12, 11, 12, …（10 枠）
- PDF 取り込みのラスタライズ解像度: `--dpi` があればその値、無ければ intake.expected_dpi。PDF は画像の解像度情報が無いものとして扱う
- `POST /api/ingest`: 別の取り込みが実行中（ロック取得失敗）のときは HTTP 409 `{"detail": "別の取り込みが実行中です"}` を返す。それ以外の応答は従来どおり結果の配列。CLI `ingest` の挙動（ロック時 `[]`・終了コード 0）は変えない
- 管理画面「今すぐ取り込み」: 409 のとき「別の取り込みが実行中です。終わってから押してください」、結果が 0 件のとき「取り込む対象がありませんでした」、1 件以上のとき「N 件処理しました」を表示する
- トンボの破線（mark_style=dashed）: PDF の各マークに実線部 mark_dash_mm・空白部 mark_gap_mm の破線を使う。各マークはカード側の端から実線部で始まる。線幅・濃さは実線のときと同じ。面付けプレビューの SVG も同じ破線（同じ比率・カード側から開始）で描く。solid（既定）のときの PDF の描画内容は変更前と同じ
- 再印刷の応答（決定 2026-11-12）
  - 1 枚でも送信に失敗したら（一部成功を含む）HTTP 400 `{"detail": "送信に失敗したシートがあります", "sheets": [...], "output": ...}`。画面は従来の「再印刷失敗: <detail>」
  - output=pdf のときは HTTP 200 `{"sheets": [{"sheet_id", "sent": true}, ...], "output": "pdf"}`（sent の意味は従来どおり「出口が成功を返した」）
  - 存在しない job_id は 404。シート 0 枚のジョブの再印刷は対象外（定義しない）
- duplicate で ok カード 0 枚のときはシートを作らない
- mark_dash_mm・mark_gap_mm は mark_style に関係なく 0 より大きい値だけを受け付ける（0 以下は検査エラー 422）
- 破線の長さは scale_x / scale_y で拡縮しない（線幅と同じく指定どおりの mm）
- 印字可能域でクリップされたマークは、クリップ後に描く線分のカード側の端から破線を始める
- layout.json の marks の形式は変えない（キー追加なし。x1,y1 がカード側である保証もしない）
- `GET /api/layout/preview` の応答は従来のキーに `mark_style`・`mark_dash_mm`・`mark_gap_mm`（mm）を加える
- 「N 件処理しました」の N は `POST /api/ingest` が返した配列の長さ（error のジョブも数える。処理済みと同一内容の重複ファイルはジョブを作らず配列にも入らないので数えない）
- PDF のラスタライズ後の画素数は `round(用紙 mm / 25.4 × dpi)`、許容差 ±1 px
- PDF 取り込みの dpi_source は `--dpi` 指定時 "option"、それ以外は "config"。PDF には dpi_mismatch を付けない

## 11.3 自動印刷の ON/OFF と印刷待ち（2026-11-12）

- 設定 `print.auto_print`（bool、既定 true）。true は従来どおり、シートができたら出口へ送る。false は output=lp のときだけ効き、シートを送らず `held`（印刷待ち）にする。output=pdf のときは auto_print に関係なく従来どおり（PDF を置くだけ・status=created）
- 対象は pipeline でシートを作るすべての経路（CLI `ingest`・launchd・`POST /api/ingest`・要確認カードの承認）
- シート status を追加: `held`（印刷待ち）・`discarded`（破棄）。従来の created / sent / error はそのまま
- held シートのカードは status を `printed` にしない（送信が成功した時点で printed）。held シートに載ったカードを、別のシートに再び面付けしない（fill の保留にも戻さない）
- held シートのジョブの status は ok のまま（review カードがあれば review）
- `GET /api/sheets?status=held`: 印刷待ちシートの一覧（sheet_id・job_id・作成日時・カード枚数・PDF のパス）
- `POST /api/sheets/{id}/print`: held のシートだけを出口へ送る。成功で sent・カード printed。送信失敗で error（ジョブも error、11.1 の規則）。held 以外のシートは HTTP 409（二度押しで2回送らない）。存在しない id は 404。output=pdf のときは送らず held のまま、HTTP 200 で `"output": "pdf"` を返し、画面は再印刷と同じ「出力先が pdf のため印刷していません（PDF は保存済み）」
- `POST /api/sheets/{id}/discard`: held のシートだけを discarded にし、載っていたカードを discarded にする。PDF は消さない。held 以外は 409
- 再印刷（`POST /api/jobs/{id}/reprint`）は held・discarded のシートを対象にしない
- auto_print を false → true に変えても、既に held のシートは自動で送らない（印刷待ち画面から送る）
- シート画像: `GET /api/sheets/{id}/image.png` は保存済みのシート PDF を PNG にして返す（印刷されるものと同じ見た目。トンボ 0.1 mm が見える解像度にする）。全 status のシートで使える
- 管理画面: 新しい画面「印刷待ち」に held シートをシート画像つきで並べ、各シートに「印刷する」「破棄」ボタン。履歴の詳細にも、そのジョブの全シートの画像を出す（output=pdf でも印刷前の見た目を確認できる）

### 11.3 の細則（決定 2026-11-12）

- カード status に `held` を追加する。held シートに載ったカードは `held`。印刷成功で `printed`、破棄で `discarded`、送信失敗では `held` のまま（シートは error）
- `GET /api/sheets`: 応答はシートの配列。各要素のキーは `id`・`job_id`（fill の混在シートは null）・`status`・`created_at`・`card_count`・`pdf_path`。`status` 指定なしは全シート、指定時はその status だけ。未知の status は 422。並びは created_at の古い順、同時刻は id の小さい順
- `POST /api/sheets/{id}/print` の応答: 成功（lp）は HTTP 200 `{"sheet_id", "sent": true, "output": "lp"}`。送信失敗（printer_name が空の場合を含む）は HTTP 400 `{"detail": "送信に失敗しました: <理由>", "sheet_id", "sent": false, "output": "lp"}`、シート error・関係ジョブ error（11.1）。output=pdf は HTTP 200 `{"sheet_id", "sent": false, "output": "pdf"}` でシートは held のまま
- print・discard の判定は、ボタンを押した時点の設定（output）を使う
- `POST /api/sheets/{id}/discard` の応答は HTTP 200 `{"sheet_id", "status": "discarded"}`。シートに載っていた全カード（fill の混在シートなら他ジョブのカードも）を discarded にし、関係する全ジョブの status を 11.1 の規則で再計算する（カードの破棄と同じ扱い）
- output=lp・auto_print=false で printer_name が空でも held シートは作る（エラーは印刷時に出す）
- 承認（approve）でシートが held になった場合の `delivery` は `{"ok": true, "error": null}`
- 再印刷で対象のシートが 0 枚（全シートが held・discarded）のときは HTTP 200 `{"sheets": [], "output": ...}`、画面は「再印刷するシートがありません」
- シート画像は 300 dpi（A4 で 2480 × 3508 px、±1 px）。トンボの位置の画素が背景（白 255）より暗い（mark_gray=0・線幅 0.1 mm で 200 未満の画素が線上にある）
- 印刷待ち画面の表示: 印刷成功「印刷しました」、送信失敗「印刷に失敗しました: <detail>」、output=pdf は 11.3 の文言。破棄は確認ダイアログ「このシートを破棄しますか？」で OK のときだけ送り、成功で「破棄しました」。409 のときは「このシートは既に処理されています」を表示して一覧を読み直す
- auto_print の値の検査は他の bool 設定と同じ（pydantic の既定の変換に従う）
- held シートの送信が失敗したとき、カードは混在 fill のシートでも `held` のまま（11.1 の「ok に戻す」より優先）。シートは error になり、ジョブの「再印刷」で送り直せる（成功でカード printed）
- カードがすべて discarded になったジョブの status は ok（11.1 の再計算で error・review が無いため）
- `GET /api/sheets` の `pdf_path` は home からの相対パス（ジョブ詳細の pdf_path と同じ形。`/files/<pdf_path>` で取れる）。`status=`（空文字）は指定なしと同じ
- print・discard の 404 は `{"detail": "sheet not found"}`、409 は `{"detail": "印刷待ちではないシートです"}`。画面は 404 のとき「シートが見つかりません」、409 のとき「このシートは既に処理されています」を表示し、どちらも一覧を読み直す
- 取り込み結果（CLI `ingest` の stdout・`POST /api/ingest` の応答）の `cards`・`sheets` は件数（整数）。11.3 で変えない
- 送信中の内部の一時状態として シート status `sending` を使う（held から送信を始めた1リクエストだけが取る）。`GET /api/sheets?status=` の指定値には含めない。再印刷の対象にしない。API サーバの起動時に残っている `sending` は `held` に戻す（CLI・launchd の起動では戻さない）
- held カードの単体破棄（`POST /api/cards/{id}/discard`）は従来どおり可。シート・PDF は変えず、その後の印刷・再印刷が成功してもそのカードは discarded のまま
- PDF のラスタライズ（シート画像・PDF 取り込み）は同時に1つずつ行う。シート画像を同時に複数要求してもサーバは落ちず、全て 200 で返す
- 印刷待ち画面・履歴詳細のシート画像は縮小表示し、クリックで原寸の PNG を新しいタブで開く。画像の近くに「クリックで原寸表示」と書く

## 11.4 別サイトからの書き込み要求の拒否（2026-11-12）

認証が無いため、ブラウザで別サイトを開いただけで、そのページから 127.0.0.1 の API へ POST が送られ、印刷・破棄・再印刷・設定変更が実行され得る。これを防ぐ。

- 対象は `/api` 配下の GET・HEAD 以外のすべての要求（9 節・11.3 の POST・PUT）
- 要求に `Origin` ヘッダがあり、その hostname が `127.0.0.1`・`localhost` のどちらでもない（`null`・解釈できない値を含む）とき、HTTP 403 `{"detail": "別サイトからの要求は受け付けません"}` を返し、処理を一切行わない（DB・ファイル・lp 呼び出しは変わらない）
- 判定は hostname だけで行う（ポート・scheme は問わない）。`Host` ヘッダとの一致では判定しない
- `Origin` ヘッダの無い要求（curl・CLI・テストクライアント）は従来どおり処理する
- GET・HEAD と `/api` 以外のパス（`/files/...`・`/`）は対象外
- 管理画面（`http://127.0.0.1:<port>/` または `http://localhost:<port>/` で開いたもの）からの操作は従来どおり動く

### 11.4 の細則（決定 2026-11-12）

- `Origin` ヘッダが存在すれば値が空でも判定の対象（空は解釈できない値として 403）。`Origin` ヘッダが複数あるときも 403
- hostname は大文字小文字を区別しない（`http://LOCALHOST:8765` は許可）。それ以外は完全一致で、末尾ドット（`localhost.`）・前後に文字が付いたもの（`127.0.0.1.evil.com`・`localhost.evil.com`）・省略表記（`127.1`）・`[::1]` は 403
- `Origin` を URL として解釈できない値（`http://[::1` 等）は 403（500 にしない）。userinfo 付き（`http://x@127.0.0.1`）や範囲外のポートを含む値でも、取り出した hostname で判定する。取り出せなければ 403
- 対象パスは、パーセントエンコードを復号した後のパス（ルーティングが照合するのと同じパス）が `/api` ちょうどか `/api/` で始まるもの。`/%61pi/sheets/1/print` も対象
- 403 の判定はルーティングより先に行う。外部の `Origin` なら、存在しない id・状態不一致・入力検査エラー・未登録のメソッド（PATCH・DELETE・OPTIONS を含む）でも 404・405・409・422 ではなく 403
- HEAD は対象外。外部の `Origin` を付けた HEAD は、`Origin` を付けない同じ HEAD と同じ応答
- 403 の応答に `Access-Control-*` ヘッダを付けない。403 をログに記録しない（アプリ自身は記録しない。uvicorn のアクセスログは対象外）
- 管理画面を 127.0.0.1・localhost 以外（`0.0.0.0`・LAN の IP 等）で開いて操作したときの画面表示は定めない（サーバは 403 を返す）
- この判定は書き込み要求だけを守る。別サイト（DNS リバインディングを含む）からの GET（`/api/jobs`・`/files/...` 等の読み取り）と、Origin を付けないブラウザ外からの要求は防がない（未対応のセキュリティ事項）

## 11.5 duplicate の繰り返し面数（2026-11-12）

duplicate で「名刺1枚を何面並べるか」を指定できるようにする。

- 設定 `print.duplicate_count`（整数 or null、既定 null、1 以上）。管理画面「設定」の「印刷」に出る（スキーマから自動生成）
- null: 従来どおり（5.3・11.2。ok カードを順に繰り返して枠を埋める）。既定は変えない
- 整数 N（timing=duplicate のときだけ効く。per_scan・fill では無視）: ok カード1枚につき、同じカードを N 面並べる
  - 並びはカードの順に、各カードの N 面をまとめて詰める（カード 1 を N 面、カード 2 を N 面、…）
  - 次のカードの N 面が現在のシートの残り枠に収まらないときは、そのカードを次のシートの先頭から置く。残り枠は空きのまま（埋めない）。カードの N 面が2枚のシートに分かれることはない
  - 1 シートの枠数は cards_per_sheet（null なら容量）。slots は載せた面数だけ（11.1）
  - 例（容量 10）: カード 3 枚・N=4 → 1 枚目 [1,1,1,1,2,2,2,2]、2 枚目 [3,3,3,3]。カード 3 枚・N=10 → 3 枚（各シートに同じカード 10 面）。カード 4 枚・N=3 → 1 枚目 [1,1,1,2,2,2,3,3,3]、2 枚目 [4,4,4]。カード 3 枚・N=1 → 1 枚 [1,2,3]
- N が 1 シートの枠数を超える指定は検査エラー（`cards_per_sheet` が容量を超えたときと同じ扱い。PUT /api/config は 422）。timing に関係なく検査する。検査エラーの文言に `duplicate_count (N) が 1 シートの枚数 (M) を超えています` を含む
- 承認（review → ok）されたカードは、そのカード1枚を N 面並べたシート 1 枚を作る。ok カード 0 枚のときはシートを作らない（11.2）
- 状態・印刷・破棄・再印刷の規則は変えない（各カードは必ず 1 枚のシートにだけ載るため）
- 1 シートの枠数より多く刷りたいときは `print.copies`（lp のとき、全シートに掛かる）を併用する
- 保存済みの設定ファイルに `duplicate_count` が無いときは null として読む

### 11.5 の細則（決定 2026-11-12）

- `card_count`（`GET /api/sheets`・印刷待ち画面の「カードN枚」）はシートに載った面数（`sheet_cards` の行数）。同じカードが複数の面に載るシートでも、面ごとに数える（N=4 で 3 枚目だけのシートなら 4）。今の duplicate（null）と同じ数え方で、変えない
- 承認で作るシートは、承認したカード 1 枚分の新しいシートを 1 枚足す。同じジョブの取り込み時に作られた既存シートは触らない・作り直さない
- `duplicate_count` に整数以外の値（`2.0`・`"3"`・`true` 等）を渡したときの受理・拒否は、`cards_per_sheet` に同じ値を渡したときと同じ（特別な扱いをしない）。1.5・`"abc"` は拒否（422）
- `cards_per_sheet` が容量を超えているときは、従来どおりその検査エラー（422・文言は従来のまま `cards_per_sheet (N) が容量 (M) を超えています`。検査は `cards_per_sheet` と `を超えています` を含むかで行う）になる。`duplicate_count` の文言も出るかは定めない
- 管理画面「設定」の項目名は「繰り返し面数」。検査エラー時に画面へ出す文言は定めない（「エラーが出て保存されない」まで）

## 12. 作らないもの

認証、複数ユーザー、eSCL 入口、カラー出力の実装、180 度の自動判定、launchd への登録（ひな形 `deploy/com.print-edit.ingest.plist` と手順のみ）。
