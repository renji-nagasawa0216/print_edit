# /st C-4 後の状態（2026-11-20）
- C-3 戻り値: tc_c3.txt（st-check ret tc OK）。TC 147件＋X 14件。U-1〜U-12 は戻り値末尾
- C-4 戻り値: judge_c4.txt（st-check ret judge OK）。判定112 / 一致107 / 不一致4（N-18,E-30,B-11,B-12）/ 判定不能1（B-13）
- judge 入力: judge_in_req.tsv / judge_in_dec.tsv / judge_in_tc.tsv / judge_in_data.md
- R10-5（文字の太さ・濃淡。段階③・対象外）を main_req.tsv と card_master_request.md 5節に追加済み

## AI 決定（先例。決定表へ追加する行。TC差分で反映）
- U-1 スロット番号: 行優先・1始まり（先例 src/print_edit/core/layout.py:161-167）。D0 の layout 具体値は test-data が決める
- U-2 review になる画像: test-data が決める
- U-3 名刺名 101字以上: HTTP 422 で拒否し保存しない。画面は alert「…失敗: <detail>」（先例 api/app.py:180, web/app.js:35,66）
- U-4 枚数 0・負・小数・空: その名刺の入力不正として作成ボタン無効。サーバーは 422（先例 api/app.py:84 pydantic）
- U-5 エラー表示: ボタン操作は alert「…失敗: <detail>」、フォームは msg 要素 class=err（先例 web/app.js:35,66,237）
- U-6 取込&作成の結果: alert。0件「取り込む対象がありませんでした」、1件以上「取り込み n件・PDF m件を作成しました」（先例 web/app.js:33-37 の alert 形式）。実行ボタン名「実行」
- U-7 並び順: 登録待ち=取込日時の古い順・idx 順（先例 store/db.py:135）／名刺マスタ=同じ／履歴=新しい順（db.py:79。job なしシートも作成日時で混ぜる）／印刷待ち=古い順（db.py:170）
- U-8 出力先 pdf での履歴の再印刷: 送らない・status 不変・alert「出力先が pdf のため印刷していません（PDF は保存済み）」（先例 pipeline.py:285-286 print_sheet, web/app.js:64）
- U-9 / B-13 シート0件のジョブの履歴詳細: 「PDF はありません」を出し、ボタンなし・エラーにしない（先例 web/app.js:99 の空表示の言い回し）
- U-10 一括の所要時間: 基準を置かない（個人ツール・同期1リクエスト）。P-02 は完了と200行のみ確認
- U-11 上書きは対象シートのスナップショットだけ置き換え、他シートの復元値は不変（M19 スナップショット決定から）。TC 追加
- U-12 移行 TC は合成データでよい

## judge（ユーザー回答待ち）J18〜J21 → 会話参照

## judge 回答（2026-11-20 ユーザー「ok, 良いです」= 全件 AI 推奨）
- J18=A: 取込&作成はその回に取り込んだ名刺だけで PDF を作る（既存の登録待ちは拾わない）→ N-18・B-11・B-12 を tc-judge 案に（N-18 は前提データで P1 を含むシートを用意する形へ）。決定表 M22 に行追加
- J19=A: E-30 を「登録した回数だけ登録待ちが減りマスタが増える（2回で登録待ち3件・マスタ2件）。再起動で戻らない」に
- J20=A: 1名刺1PDF の名刺切替プレビュー・複数 PDF 時の上書き不可は決定表どおり実装。絵は追加しない（凍結前チェック: 食い違い→ユーザーが決定表を正と判断）
- J21=A: 出力サンプル（会話で提示した表）承認。正本の ## 出力サンプル にそのまま載せる

## 次の手順
1. 決定表（tc_decided.txt の決定表＋上の AI 決定 U-1〜U-12・J18）に行追加 → st-check ret tc --decided
2. spec-tc（sonnet・新規）を モード=TC差分 で: 変わった決定行・影響 M（M22,M7,M8,M17,M24,M4,M9,M27,M19）・旧 TC（tc_c3.txt）。N-18,B-11,B-12,E-30,B-02,B-13,P-02 等を変更、U-4/U-6/U-7/U-11 の TC 追加
3. 追加・変更 TC のうち判定対象だけ tc-judge（opus・新規）
4. C-5 正本 ai_docs/specs/main.md 組み立て（st-check spec --base main --repo --req、ret judge --spec）→ Phase D 報告（judge は回答済み）→ /vf --pre → /im

## 進捗（2026-11-20 セッション2）
- 手順1 完了: st2/tc_decided.txt（st1 の写し）に決定行を計19行追加（U-1〜U-11・J18 の15行＋U-5/U-7/U-13/U-14 残りの4行。M6,M9,M19,M22）。決定表 118行。`st-check ret tc --decided < st2/tc_decided.txt` exit 0・FAIL 0・WARN e1 94。U-2・U-12 は決定表に入れず正本の「実行前提」へ
- 手順2 完了: spec-tc（TC差分）2回。戻り値 st2/tc_diff1.txt（変更10・追加16: N-95〜N-104, E-31〜E-35, X-15・前提データ差分 D1追記,D1o,D1s,D1i,D2o,D3a,D3b,D6n,D7o,D8）と st2/tc_diff2.txt（変更8: N-12,N-13,B-05,E-05,E-22,N-96,X-02,X-05・追加4: N-105,N-106,E-36,E-37。X-02/X-05 はメインが5列に整形）。旧 TC で変更されたもの計17件（N-96 は diff1 で追加→diff2 で変更）、追加20件、欠番0
- 残った未定義: U-5 の <detail> 具体文言・U-15 新規保存 API パス・U-16 一括登録/破棄の失敗行の中身 → 実装判断ログで実装時に決める（TC は検証語「失敗:」「P1 の行が1行」までで成立）。U-1/U-2/U-17 は test-data
- verify-base denials: 2026-11-20 分 0件（C-3・C-4 とも）
- C-5 準備: /private/tmp/claude-501/-Users-renji-Projects-private-print-edit/6ad6bb46-d29b-4424-8369-0979c6e6706c/scratchpad/c5/ に build.py（未実行。usage: python3 build.py <out.md> st2/tc_diff1.txt st2/tc_diff2.txt）・head.md（目的・対象外）・sample.md（J21 出力サンプル）・premise.md（実行前提）。log.md（## 実装判断ログ。仕様変更 1行＋U-5/U-15/U-16 を実装で決める旨）は未作成。build.py は io.txt の「要決定」14セルと J18 に反する情報源1セルを決定表の決定へ置換する（Phase D 報告に件数15を書く）

## 次の手順（更新）
3. tc-judge（opus・新規）: 判定対象＝変更17＋追加20のうち、リスク高 M の全 TC＋リスク中 M（M4,M14,M18,M30）の異常系・境界値。入力は judge_in_* 形式（judge_in_req.tsv・judge_in_dec.tsv を決定表の追加19行ぶん更新・judge_in_tc.tsv を対象 TC に差し替え・judge_in_data.md に前提データ差分を追記）。spec-tc の根拠・注記は渡さない
4. log.md を書いて build.py 実行 → st-check spec --base main --repo /Users/renji/Projects/private/print_edit --req /Users/renji/Projects/private/print_edit/ai_docs/specs/main_req.tsv・ret judge --spec → ai_docs/specs/main.md 保存 → Phase D 報告 → /vf --pre → /im

## 進捗（2026-11-20 セッション3）作業 dir J5=/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/c9211e62-4328-4118-ad1d-13d215a24745/scratchpad/j5
- 手順3: tc-judge（opus）判定30件 全一致（J5/judge_c4b.txt・ret judge OK）。旧112件とマージ → J5/judge_all.txt 128件全一致・ret judge --spec OK（draft_t1 時点）
- C-5 形式検査で FAIL e3 4件（リスク高 M3,M21,M25,M29 に異常系・境界値なし。C-3 からの欠落）→ spec-tc 新規で追加6件 J5/tc_diff3.txt（E-38〜E-41・B-17・B-18）
- 追加6件の tc-judge（J5/judge_c4c.txt・ret judge OK）: 一致4 / 不一致 E-41（登録待ちは PDF 作成に使えない＝M17）/ 判定不能 E-38（review バッジ・取り込みのみの通知が未決定）→ 先例で決定し judge には出さない
  - 決定表に2行追加（st2/tc_decided.txt、計120行。変更前の写し J5/tc_decided_before_e38.txt）: M3 取り込みのみの結果表示=alert「n 件処理しました」/0件「取り込む対象がありませんでした」（先例 src/print_edit/web/app.js:37）、M4 review カードのバッジ=付けない（先例 mock/06_ingest/data.json）
  - spec-tc 新規で E-38・E-41 を作り直し＋E-39（前提 lp と D2 の pdf の食い違い→D2l 新設）・B-18（D3→D3b）→ J5/tc_diff4.txt（変更4・前提データ D2l）
- WARN a/b 対策: J5/fix_sections.py（build.py 出力に後掛け。前提データ見出し分割・欠番行を ## テストケース 直下へ）
- c5/log.md 作成済み（仕様変更行・e3 補完行・E-41 確認箇所・U-5/U-15/U-16）。E-38 n に review を数える件も先例 app.js:37 で決定済み（log 未記載→追記する）
- 最新草稿 J5/main_draft4.md: build.py ＋ diff1〜4 ＋ fix_sections。決定表120・TC 187（N106/E41/B18/P3/T4/X15）。st-check spec FAIL 0・WARN e1 95
- judge 入力 J5/judge_in_{req,dec,data}.md|tsv（dec は120行で再生成済み・data は D2l 未追記）。生成スクリプト J5/mk_judge_in.py

## 次の手順（セッション3 更新）
1. judge_in_data.md に D2l 行を追記し、E-38・E-39・E-41・B-18 の4件を judge_in_tc3.tsv にして tc-judge（opus・新規）
2. 不一致・判定不能が出たら先例探し→決まらなければ Phase D の judge へ
3. 判定をマージ（judge_all.txt の E-38〜E-41・B-17・B-18 を judge_c4c＋新判定で置換・追加）→ ret judge --spec J5/main_draft4.md
4. c5/log.md に E-38 n の決定と M3/M4 追加行（仕様変更）を1行追記 → 再ビルド → st-check spec → ai_docs/specs/main.md 保存（現在は存在しない）
5. Phase D 報告（凍結前チェック: 決定表⇄画面イメージ=一致（mock 01 の「実行」）・空表示/並び順は絵に無く対象外 / 地雷帳なし。出力サンプル J21 承認済み。tc-judge 補足: E-12 で既存「既定」編集時の cards_per_sheet NULL 保持は未検証）→ /vf --pre → /im

## 進捗（2026-11-20 セッション4）
- 手順1: tc-judge（opus）E-38・E-41・E-39・B-18 → 4件一致（J5/judge_c4d.txt・ret judge OK）。入力 J5/judge_in_tc3.tsv（J5/mk_judge_in3.py）・judge_in_data.md に D2l 追記
- 手順3: J5/judge_all.txt 134件全一致（旧128件は J5/judge_all_128.txt）・ret judge --spec OK
- 手順4: c5/log.md に M3/M4 追加行の仕様変更1行追記 → J5/main_draft5.md（決定表120・TC187）・st-check spec FAIL 0 / WARN e1 95（J5/check_spec5.txt）→ ai_docs/specs/main.md に保存
- advisor: Phase D は★（M3 は変更マップ M の現行挙動を先例にしており先例扱い不可・出力サンプルに取り込みのみの行が無い）。J22（M3）・J23（M4）をユーザー judge に提示。回答後: 出力サンプルに「取り込みのみの結果」行を追加し main.md を更新 → /vf --pre → /im
- E-39/E-17 の操作欄に PDF 作成画面への遷移が無い件: D2 系 TC 約50件が同じ書き方（「C1=7・C2=6」等）のため直さず、Phase D 報告に記載
- Phase D 回答: J22=A・J23=A（「judgeは推奨で問題ありません」）→ sample.md に行追加（写し c5/sample_before_j22.md）・J5/main_draft6.md → main.md 保存（FAIL 0・WARN e1 95・ret judge --spec OK）。次: /vf --pre

## /vf --pre（セッション4）
- 方式: advisor 判定で C（併用）。API・DB・CLI・PDF の TC = test-data が pytest（tests/unit/test_spec_main.py 想定。先例 test_spec_11_8c.py・test_api.py の TestClient+tmp_path home）、画面の TC = /qkit:pw（pw-all.sh --pre → pw-gen → pw-red.sh）。振り分けはメインがしない（基準役側。172件で重なり・漏れを件数照合）。却下: A pytest のみ（UI 118件/172 が Red 分母外）・B Playwright のみ（SQLite・PDF ラスタ・CLI を見られない）
- Step 0 済: verify_base=main・.vf は git 除外済み・e2e/ は無い（pw-bootstrap --check「e2e が無い」）・e2e/ は git 除外されていない（--fix が .git/info/exclude に追記する）・.vf/red 無し・.vf/seed あり（旧周回の残り。削除しない）
- 次: (1) pw-bootstrap --fix（npm install・playwright install chromium）→ ログイン無し案件の auth.setup.ts（MANUAL）を案件 e2e/ 側で no-op 化（qkit 本体は直さない）(2) seed 方式: 毎回新しい一時 --home を作り 8765 以外のポートで serve、BASE_URL=http://127.0.0.1:<n> (3) test-data（pytest 分）と pw-all.sh --pre を進める (4) Red 報告は pytest（fail/skip/pass）と Playwright（期待不一致/要素未検出/既にpass/環境/生成不可）で分け合計172
- 報告に残す: 旧正本 11.8（skip 24）・11.8c（skip 7）の DOM TC が判定記録なし（今回の範囲外）

## /vf --pre（セッション5）
- pw-all.sh は --spec を受けない（ブランチ main から正本を決められない）→ 下位を個別に呼ぶ。順序（advisor）: pw-env --spec ai_docs/specs/main.md --pre → pw-tc（済: .vf/pw/tc.tsv。187件 = include 165 / exclude 22・書込系 58）→ pw-tc --skeleton > e2e/tests/main.pw.spec.ts（1回だけ）→ pw-gen → pw-check（seed dir・--options）→ pw-red --spec。共有ファイル（playwright.config.ts・auth.setup.ts・bt_config.md）は pw-red 前に確定済み。後で変えると pw-loop exit 3
- 済: mkdir e2e・pw-bootstrap --fix（全 OK）・.git/info/exclude に e2e/ 追加・e2e/tests/auth.setup.ts（no-op）・e2e/bt_config.md（ログイン無し）・e2e/test-accounts.local（BASE_URL=http://127.0.0.1:8899 ダミー）・playwright.config testIdAttribute 'name'→'data-key'（DOM 契約が data-key/data-section/data-sheet）・verify-base set 7aacd05（/im の main commit で基準が動くのを防ぐ）
- 済: 偽プリンタ .vf/fakebin_main/{lp,lpstat,lpoptions}（lpstat -e は PE_FAKE_PRINTER 1件、lpoptions は0件、lp は lp.log へ追記）
- 済: helper e2e/tests/helpers/home.ts（配管のみ・値を持たない）。TC ごとに .vf/home/main_<RUN>/<TC>_r<retry> → `sh .vf/seed/main.sh <TC> <home> pre` → .venv/bin/print-edit serve（ポート 8900+parallelIndex*20 から、PATH 先頭 fakebin_main、detached・teardown で kill(-pid)）→ `sh .vf/seed/main.sh <TC> <home> post <baseURL>`。シード stdout の `PENDING <TC> <理由>` を .vf/pw/seed_status.tsv に記録。失敗は "seed failed:" / "ECONNREFUSED" で throw（環境分類）。fixture timeout 60s。未実行（シードが無いため動作未確認）
- serve は起動時に inbox を取り込まない（HEAD cli.py:84-90 は home.ensure のみ）
- advisor 判定（シード方式）: (c) 変形。test-data に今書かせる = スキーマ非依存の前提（D4・D4a〜d の旧形式 DB/config、D6・D6n・D1i の inbox 画像、D0 の config.json は 7aacd05 にあるキーだけ）＋DB 行が要る D1〜D3・D5・D7・D8 等は正本の値だけの宣言ファイル（.vf/seed/data/*.tsv）。main.sh はデータが要る TC ID を全件 case に持ち（pw-check seed マーカー）、未投入分は `PENDING` を出して exit 0。実装後に新規 test-data が宣言ファイル→実 sqlite スキーマへの写しだけ書く。pytest も同じ宣言ファイルを使う（.vf/ 配下に置く）。pytest も Red を回し件数を別記録
- 次: (1) test-data 起動（モード通常。資料: 正本 ai_docs/specs/main.md・helper のシード契約（上記の引数・PENDING 行・pre/post）・pytest 分は .vf/pytest/ へ・7aacd05 の旧スキーマは git show 可）と pw-gen 起動（SPEC_PATH TEST_FILE=e2e/tests/main.pw.spec.ts TC_TSV=.vf/pw/tc.tsv SELECTORS=なし BT_CONFIG=e2e/bt_config.md HELPER=e2e/tests/helpers/home.ts）を並行 (2) pw-check（--options は 7aacd05 sqlite スキーマから pw-schema 書式で作る）(3) pw-red（run_in_background・出力 .vf/pw/red.out）＋ pytest Red (4) 報告: Playwright 分類別・pytest 別・データ未投入で落ちた TC 数（seed_status.tsv）・生成不可・既にpass、合計172照合 → advisor → /im
- 報告に残す: 旧正本 11.8（skip 24）・11.8c（skip 7）の DOM TC 判定記録なし／pw-all が --spec 非対応（qkit 改善候補）
- ユーザーへ出す業務判断（advisor #13）: Green（実装後の pw-loop）をメインで回すと書込系 58 件が --grep-invert で未実行・シードも流れない。TC ごとに一時 home なのでメインでも安全だがスクリプトは知らない。選択肢: wt で Green／未実行のまま報告／pw-run --all を直接使う

## /vf --pre（セッション6・wt issue1）
- Red の数え直し（advisor 判定「修正してから続行」）: Red（データあり）約12 = pw 12（D4 系10: N-14・N-16・N-17・N-38〜N-43・N-78 ＋ D0 の N-01・N-02）＋ pytest 2（N-16・N-43）／Red（シード待ち）pw 77・pytest 8（`Failed: PENDING`）／既にpass 2（E-26・B-14）／不明 1（E-14 は D0 PENDING で config.json が無いだけ→シード待ちに再分類）／未テスト 78。シード待ち 85件は旧コードで Red を確かめる手段なし（新スキーマ要）→ Green 報告に引き継ぐ
- REGEN推奨=はい は要素未検出の件数しきい値のみ→再生成しない。Green は Red の spec＋pw-triage
- 書込系 58 件の問いは不要: pw-loop.sh:66-70 は IS_WT=false のときだけ除外。wt は IS_WT=true
- .vf/seed/main.sh を #1_main.sh に改名しない（pw-env.sh:80 で SEED_FILE が立ち、pw-loop が引数なしで呼んで exit 2）
- E-26・B-14 は tc-judge へ（並行）。実装後: test-data で宣言→実スキーマ写し（E-14 を pw・pytest 両方で再判定）→ helper 追加 → pw-gen は SKIP 分のみ（既存87件・.vf/red は触らない。後付けブロックが pw-expect 固定で守られるか要確認）。全件 SKIP の describe 7（S7・P1・S1・H2・S3・JB・S4）は最終報告に件数で残す
- /im に渡すのは正本・mock/*/inject.js（DOM 契約）・禁止事項のみ。U-15・U-16 の API パスは implementer に「ルート一覧」として報告させ、test-data へはパス名だけ渡す

## /vf --pre（セッション7・wt issue1）
- advisor（再点検）「修正してから続行」→ 件数訂正のみ。セッション6の「約12/pw77/pytest8/既にpass2」は誤り（合計179）。確定: Red（データ非依存）12 / シード待ち 79（pw 73・pytest のみ 6）/ 既にpass 3（E-26・B-14・N-94、判定材料外）/ 未テスト 78 = 172
- J24 未回答のまま /im へ。implementer には「0件時のバー表示は未決（J24）。A（出さない）を仮置き・1箇所の条件分岐・file:line 報告」
- E-26 TC 強化の /st は /im 後（spec-tc に実装差分・/im 結果を渡さない）

## /vf Green（セッション8・wt issue1）
- advisor（経路）「修正してから続行」: 折衷。recon（契約検証・selectors.tsv）は省略不可→実施。smoke は省略（ログイン無し・recon で代替）と報告に残す。Step 4-5 は REGEN 全件再生成せず Red の spec＋pw-triage（qkit SKILL.md:34）。pw-all.sh は recon 前に回すなら --resume 4 必須（引数なしだと ROUTE=recon+gen で spec 上書き）。SKIP 78 件だけの再生成手段は無い→試行 spec（PW_SPEC_OUT='#1_main.skip.pw.spec.ts' PW_VF_DIR=.vf/skip）で別途。要素未検出 40 件以上残れば recon 欠落表を見直す
- recon: 一時 home（scratchpad 27c0f746…/recon_home1、seed N-75=D3+inbox3+notcard）・serve port 8791（fakebin_main を PATH 先頭）。browser-test RECON=true 契約検証で起動中
- 次: 3-3 ゲート（manifest ai_docs/documents/main/mock/manifest.md）→ pw-all.sh --resume 4 --until 4 → pw-all.sh（bg, .vf/pw/green1.out）→ pw-triage → pw-loop --final
- 別経路の分類報告が到着（このセッションで起動していない agent。scratchpad 0ec27344…/run1/classification.tsv）: S219/R183/P45/B36/未確定1=484。B1（26件・home.py の旧 config 移行）は修正前の状態での報告（handoff 3節で修正済み）。新規の論点は B2（10件）: 11_8 N33・N36・N39・B09・B10・N72／11_6 B20／11_3 N02／cli_pipeline test_ingest_end_to_end・test_ingest_duplicate_and_lock で jobs/<job_id>/sheets/*.pdf が0件（報告者は pipeline.py:240 が jobs/_pdf/sheets/ に書くと指摘、根拠 M22 は出力先の記載なし・確度中）。未検証。/vf Green 後、J25 回答と合わせて扱う（handoff 3節の分類 cls2.tsv と食い違うため、どちらを正とするかは未判定）
- recon run1 完了: png 26・selectors 161行（未取得35）・errors 0・契約差分24行（.vf/recon/contract_diff_run1.tsv）。メイン分類（正本 grep）: 正本優先でモック古い 7（一括印刷/一括破棄/一括登録の文言6・04 cards_per_sheet は N-35/J9 で含む）／正本どおり 1（既定値として保存→上書き保存・別名で保存）／前提データで未到達 9（06 個別・画像、08 追加・スロット差し替え・超過）／モックにだけあり正本・改修前アプリに無い 7（01 ダイアログ「対象: 未取り込みの画像 n 件」・06「画像を選んで取り込む」「最終取り込み」「未取り込み n 件」・03 ページ内確認 UI 3行＝実装はネイティブ confirm）／差分でない 1
- 再 recon（06=D1 port 8792・08=D2 port 8793、home は scratchpad recon_home2_d1・recon_home4_d2）を browser-test で起動中 → contract_diff_run2.tsv。結果後に advisor へ 3-3 ゲート判定（モックのみ 7 行を /im 差し戻すか judge J26 にするか）
- advisor（3-3）「修正してから続行」: 絵との pc/sp 突合が未了（after 42行中 recon png 欠け7枚）→ 追加撮影（browser-test、03 は D7 port 8794）→ 全 after 行の突合表。分類: 03 ページ内確認3行は /im（M27/M28 件数つき確認＋承認絵 #15/16）／06「画像を選んで取り込む」は M3「取り込みのみ」で置換済み→差し戻さない／01「対象: 未取り込みの画像 n 件」・06「最終取り込み」「未取り込み n 件」は J26（推奨: 絵で承認済みのため実装／代替: 正本に表示しないと追記）／08 追加ボタン・06 個別破棄確認なしは差異なし（モック初期は検索欄 "20261114"・06 inject に confirm 0・M6 は一括のみ）／06 バッジ2行は前提データで未到達・N-14/N-18/N-72 で担保
- SKIP は 90 件（ユニーク）でメモの 78 と不一致→原典確認。N-05・E-38（取り込みのみボタン）と確認方式 SKIP 8件（N-12 N-13 N-62 N-85 N-87 N-88 B-05 B-15）は試行 spec で再生成対象
- recon サーバー 8791〜8794 は 3-3 後に止める（8781 は /mk 土台。触らない）
- SKIP 実数（e2e/tests/#1_main.pw.spec.ts の行頭 "// SKIP: "）: 90 行 = B6・E16・N46（生成不可 68）＋ P3・T4・X15（exclude 22）。test( は 87。メモの「未テスト 78」とは 10 差で原因未確認（advisor の 90 は SKIP 行総数）
- 追加撮影（03 選択 sp・結果 pc/sp、04 sp、08 sp・拡大 sp・列優先 sp）を browser-test で実行中（03 は 8794 D7 で結果まで確定可と指示）
- 追加撮影 7枚 ok（.vf/recon/03_held_bulk_選択_sp・結果_pc・結果_sp・04_preset_editor_sp・08_pdf_create_sp・拡大_sp・列優先_sp）。注: 08_拡大_sp は幅 1629px（他 sp は 1170px）→ sp で横はみ出しの疑い（突合で確認）。03 結果 sp は pc 後の残り2件で実行。8794 の D7 home は一括印刷で消費済み
- 次: manifest after 全42行 × recon png の pc/sp 突合表（照合役を新規起動・コンテキストを渡さない）→ 分類表更新 → /im 差し戻し（03 ページ内確認＋視覚差異）・J26 をユーザーへ → /im 後 recon 撮り直し → 試行 spec で SKIP 10件 → Step 3.5 → pw-all

## /vf Green（セッション9・wt issue1）
- 冒頭で J24・J25・J26 を全文提示（J26 は初出。03 ページ内確認とネイティブ confirm の方式統一も添えた）。いずれも未回答
- 3-3 突合表を verifier（新規・パスのみ）に依頼 → .vf/recon/mock_compare.tsv
- 突合結果（.vf/recon/mock_compare.tsv）: after は 42 ではなく 32 件（第1 18・第2 14）。一致2・差異26・判定不可4・対応なし0。超過_pc は列優先_pc と同一ファイル（md5）
- メイン分類: 正本どおり・モック古い（一括文言・1枚あたり枚数・上書き/別名保存・保存方法欄・取り込みのみ）／データ差（#17・#21・#24・#31・拡大ボタン追加）／/im 15行＝.vf/recon/im_return.tsv（視覚・静的文言・03 確認モーダル・sp はみ出し 08=543px・05=411px）／J26 待ち（#5,6,29,30 ＋新規「フォルダ監視: 稼働中」）／判定不可→撮り直し（#9,10 取込ジョブ詳細・#29,30 登録待ちカード・#33,35,37,40 名刺0件・#38 列優先 sp）
- advisor（3-3 分類・/im 方針）に照会中
- advisor（3-3）「修正してから続行」8件を反映: im_return から #6（正本 :207 失敗0件は成功件数のみ）・#15（manifest:123 注記はダイアログの代用）を削除。#14 は承認絵の文言のみ。追加 #16 PDF作成の1枚あたり枚数欠落（J9・manifest:160）・#17 設定作成の既定値一覧の枠。#5 確認モーダルはページ内モーダルに固定（J26 の添え書きは予定で問いではない）。失敗ありの結果表示は判定不可→失敗を含むデータで撮り直し。上書き確認は Playwright の dialog で確認
- #38 列優先: 撮り直しを待たず verifier（8793）で DOM のスロット印を読む → 行優先なら im_return へ追加
- #38 列優先: verifier が DOM（#pv-svg g[data-slot] 座標）で確認→ pc/sp とも M17 :109 どおり（一致）。recon 画像の撮影状態の問題。差し戻さない。sp scrollWidth 543 は再現（im_return 12 行目）。im_return 確定 15 行 → /im
- /im（修正モード・opus・MODEL_ESCALATION）を bg 起動。範囲: im_return 15行。#5 は印刷待ち一括の2つだけページ内モーダル（他のネイティブ confirm は spec が dialog で待つので維持。N-85/87/88 は確認方式不明で SKIP 中＝試行 spec で再生成）。J24 分岐・J26 項目は触らない
- /im 完了: app.js・style.css のみ。15行中 12 直した・#3 CSS のみ（要撮影確認）・#11 名前行は残す（N-92 が要求。実装判断ログ追記）・#14 変更なし（job_id NULL は省く。ジョブ由来シートで撮り直して確認）。cross 件数一致・quartett-lint 0・node --check OK。残: 06 sp の inbox_dir（app.js:147）はみ出し疑い→撮り直しで確認
- 撮り直し: 新 home（scratchpad 48666a9d…/recon2/{d1,d2,d3,d7}、seed N-06/N-19/N-27/N-85 pre、exit 0）を serve 8795=D1・8796=D2・8797=D3・8798=D7（fakebin_main 先頭）。verifier（新規・パスのみ）が撮影＋再突合 → .vf/recon/r2/・.vf/recon/mock_compare_r2.tsv。失敗行の結果表示は再現不可（fake lp exit 0。X-03）
- 旧 recon 8791〜8794 は停止済み（8781・8150 は稼働のまま）
- 再突合 r2 完了（.vf/recon/mock_compare_r2.tsv 67行: 一致19・差異47・判定不可1＝失敗行再現不可）。sp scrollWidth は全撮影 390（はみ出し解消）。verifier の自己分類: 承認（J1・J3・J5・J9・スロットは容量分）で実装が正 約14／絵の欠落・データ起因疑い 約7
- r2 で新たに出た不具合候補（未分類・正本未照合）: (1) 履歴の詳細でシート行が「[object HTMLDivElement],…」と文字列化・調整するボタンなし（#9,10。前回は PDF ジョブを開いて判定不可だった）(2) 履歴詳細のカード番号が #0 起点（絵は #1）・原画像 404（シード起因か未断定）・sp でカード並びずれ (3) 一括印刷成功後も held のまま一覧に残る（D7 は出力先 pdf。正本 N-85 の期待と照合要）(4) PDF 作成の補正・面付けが常時展開（J4 折りたたみ・既定で閉じる、を正本で確認）(5) 拡大に赤破線・容量見出し・スロット選択枠なし（M13「容量表示つき」と照合）(6) 名刺マスタの選択強調が青枠（絵は灰背景＋濃い枠。im_return 外）(7) PDF 作成 sp の使う名刺行の折り返し（scan_a.jp/g）
- 既決で差異扱いにしない: 一括文言・取り込みのみ・名前の二重表示（N-92 で残す）・上書き確認注記（manifest:123）・結果要約「成功 3件」（:207）・稼働中/最終取り込み（J26 待ち）
- #41,42 は JA のシート行が描画されない（=(1)）ため job_id なしの PDF 作成 #7 から開いた → (1) 修正後に撮り直し
- 次: r2 の差異 47 を正本 grep で分類（上の既決を除く）→ advisor → /im（修正モード・MODEL_ESCALATION）に (1)〜(7) のうち実装バグ分 → 該当画面だけ撮り直し（サーバー 8795〜8798 は稼働中。8798 D7 は一括印刷で一部消費）→ SKIP 10件の試行 spec → Step 3.5 → pw-all.sh --resume 4 --until 4 → pw-all.sh（bg）→ pw-triage → pw-loop --final

## /vf Green（セッション10・wt issue1）
- 冒頭で J24・J25・J26 を handoff_4 の記載どおり全文再掲。未回答
- r2 差異 47 行の分類を investigate（新規）へ依頼 → .vf/recon/r2_classify.tsv
- 分類完了（.vf/recon/r2_classify.tsv）: 既決22・視覚差10・実装バグ6・データ起因6・モック古い3。バグ B1 履歴詳細シート行の配列直渡し（N-79/N-81/M24）・B6 補正/面付け折りたたみ（manifest:155 J4）。視覚差 B2 #0起点・B3 履歴詳細sp並び・B4 登録待ちカード横並び・B5 名刺マスタ選択強調・B7 拡大ボタン/プレビュー列（低）・B8 使う名刺行の折返し・B9 拡大の赤破線/高さ（低）。(3) N-85 は held のままが正。原画像 404 は seed 起因と確定（recon2 の全 home で jobs/*/source.* 0件）
- 次: advisor（/im 範囲）
- advisor（/im 範囲）「修正してから続行」9件反映: B2（#0 起点）はシード D2o の idx 0 始まり起因（detect.py は1始まり）→データ起因・差し戻さない。B3 は原画像 404 起因の可能性→home に jobs/<JA>/source.png を置いて撮り直し、ずれれば /im。B6 は PDF 作成側だけ折りたたむ（presetFields・設定作成は N-35 が group 表示を確認するため不変）。J4 は正本本文に無く TC も無い→残課題「正本に J4 なし」。B7・B9 は差異として報告に残す（赤破線は改修前からの表示）。撮り直しに 08 調整から開く pc/sp（JA のシート行から）を追加・新規 verifier で。8798 D7 消費は印刷待ちを撮らないので影響なし
- .vf/recon/im_return_r2.tsv 5行（B1・B6・B4・B5・B8）→ /im
- /im（修正モード・opus・MODEL_ESCALATION）bg 起動。範囲 im_return_r2 5行。完了後: im-check cross 再実行・quartett-lint・node --check → 撮り直し（JA の home に jobs/<JA>/source.png を置く・08 調整から開く pc/sp を追加・新規 verifier）
- /im 完了: app.js（B1 :257 展開・B6 :856-861）・style.css（B4/B5/B8・.sheet-line）。cross 件数一致（全21）・quartett-lint 出力0・node --check OK。e2e の補正/面付け参照は設定作成 N-35（:445-447）のみ。実装判断ログ追記済み。summary 文言「項目を表示」は仮
- 次: 撮り直し（新規 verifier）
- 撮影用 home の JA/JB（d1,d2,d3,d7）に source.png を生成（scratchpad 34558b09…/mk_source.py、cards/*.png を白地に並べたもの）
- 撮り直し r3 を verifier（新規・パスのみ）に依頼: 02 履歴詳細・06・07・08（通常・調整から開く）pc/sp → .vf/recon/r3/・mock_compare_r3.tsv
- ユーザー指示「一旦停止して良いです、使用量がえげつない」で r3 撮り直しの verifier を途中停止（部分結果は使わない。.vf/recon/r3/ に途中の画像がある場合は再撮影時に別名 r4/ へ）。serve 8795〜8798 は稼働のまま
- 再開時: 撮り直し（r3 からやり直し）→ serve 停止 → SKIP 10件の試行 spec → Step 3.5 → pw-all.sh --resume 4 --until 4 → pw-all.sh（bg）→ pw-triage → pw-loop --final
