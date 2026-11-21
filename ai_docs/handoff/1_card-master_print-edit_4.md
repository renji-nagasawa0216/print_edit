# #1_card-master 引き継ぎ（2026-11-20）

## 1. 環境
- 作業ディレクトリ: `/Users/renji/Projects/private/print_edit/.worktrees/issue1`（main の作業ツリー内の wt。起動ディレクトリからは相対 `cd .worktrees/issue1` を単独で）
- ブランチ: `#1_card-master`（ベース main 7aacd05。番号 1 は名目上）
- 前の handoff: `/Users/renji/Projects/private/print_edit/.worktrees/issue1/ai_docs/handoff/1_card-master_print-edit_3.md`（2・5節以外の古い事実はここ。3節に無いことはこのファイルから辿って grep する）
- 用途: `print-edit`
- 差分: 8 files changed, +1558/−355 ＋ ?? src/print_edit/arrange.py（未コミット）
- 撮り直し用 serve（稼働中）: 8795=D1・8796=D2・8797=D3・8798=D7（D7 は一括印刷で一部消費）。home=/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/48666a9d-bc30-4818-b950-cdb63e2229af/scratchpad/recon2/{d1,d2,d3,d7}（seed N-06/N-19/N-27/N-85 pre、PATH 先頭 .vf/fakebin_main）。旧 8791〜8794 は停止済み。8781（/mk 土台）・8150（本番）は触らない
- 個人プロジェクト（Python 3.12・uv・FastAPI・SQLite・素の JS。ログインなし）。remote なし

## 2. ユーザーの指示（逐語）
- 前の handoff 2節は全件有効（`1_card-master_print-edit_3.md` 2節 → `_2.md` → `1_card-master_print-edit.md` → `main_print-edit_28.md` 2節。/go 起動「このpj要件を改修したい。割と大幅な回収になるので、先に要件定義して実装してもらおうかと思います。」・「ただwt作成する必要もないので、今回はbで進めて問題ありません」・J10・J13・R10-5「ではa,bどちらもで。」・J18〜J21「ok, 良いです」・J22/J23「私は指示出ししていないですね、judgeは推奨で問題ありません」・「すいません、advisorに委ねる絶対条件ってどこにありますか？それ削除して良いです」ほか）
- pw-gen 経路の judge への回答: 「A: wt を作る」
- wt の番号・/im も wt で行うかの確認への回答: 「任せます」→ 番号 1・/im も wt・最後に main へ取り込み
- 今回のセッションでユーザー発言なし（auto-relay 1/5 のみ）

## 3. 確定した事実
- 作業状態の正本: `/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/c92d8efd-1326-4d2d-b628-02740df6da4e/scratchpad/st2/gate_state.md`「## /vf Green（セッション9・wt issue1）」（必ず全文 Read。r2 の不具合候補 (1)〜(7) と既決リストはここ）
- 3-3 突合 run1（verifier）: manifest の after は 32 件（handoff_3 の「42」は誤り）。.vf/recon/mock_compare.tsv（一致2・差異26・判定不可4）
- advisor（3-3）「修正してから続行」8件を反映して .vf/recon/im_return.tsv を 15 行で確定（#6 結果要約は正本 :207「失敗0件なら成功件数のみ」で削除、#15 上書き注記は manifest:123 でダイアログの代用なので削除、#16 PDF 作成の1枚あたり枚数＝J9・manifest:160、#17 既定値一覧の枠を追加）
- #38 列優先: verifier が DOM（#pv-svg g[data-slot] 座標）で確認し、pc/sp とも M17 :109 どおり（差し戻しなし）
- /im（修正モード・opus。hook agent-call-guard は委譲文の先頭行に `MODEL_ESCALATION: 修正モード` を要求）: 変更は app.js・style.css だけ。15 行中 12 行を修正、#3 は CSS のみ、#11 の名前行は残す（N-92 が一覧での文字表示を要求）、#14 は変更なし（job_id が NULL のシートはジョブ ID を省く）。confirmDlg（app.js:265-276、#confirm-dialog.overlay>.dlg）は印刷待ち一括の2つだけ。他はネイティブ confirm（spec が dialog を待つ。N-85・N-87・N-88 は確認方式不明で SKIP 中）
- 検収: im-check.sh cross の件数は報告と一致（bulk-confirm 全2/変更2・path-display 全2/変更1・preset-fields 3/3・arrange-fs 3/3・pv-svg 3/3）。quartett-lint の出力 0 件。node --check OK
- 実装判断ログ（ai_docs/specs/#1_main.md 末尾）に1行追記済み（名前行の維持・job_id NULL の扱い・確認モーダルの範囲・M11 注記）
- 再突合 r2（verifier）: .vf/recon/mock_compare_r2.tsv 67 行（一致19・差異47・判定不可1）、画像は .vf/recon/r2/。sp の scrollWidth は全撮影で 390（はみ出し解消）
- zsh では `set -- $x` が単語に分割されない（seed ループが exit 1 に。`${pair%%:*}` で回避。空フォルダ "d1 N-06" 等が recon2/ に残っている）

## 4. 未確定・仮説
### ユーザーへの確認事項
- 問い（J24・M28 印刷待ち）: 印刷待ちが0件のとき、一括操作のバー（全選択・一括印刷・一括破棄）を出しますか
  - 背景: tc-judge（セッション6）が B-14 を「弱い」と判定。正本 :225 の0件列にバーの記述が無く、文言だけでは改修前と見分けられない
  - 選択肢: A 0件ではバーを出さない（B-14 は Red を求めないデグレ確認 TC と明記）／B バーを出し一括印刷・一括破棄を disabled（B-14 に「disabled のまま」を足して Red にできる）
  - AI 推奨: A（承認済み mock 03 に0件の絵が無く、空の一覧に操作バーを出す利点が小さい）
  - 未回答の間の扱い: implementer は A を仮置き済み。/vf は止めない
  - 状態: 質問済み（セッション6）・未回答（セッション9 冒頭で全文再掲済み）
- 問い（J25・M15/M5/M24 既存テスト）: 改修で落ちる既存テスト 484 件を誰が直しますか
  - 背景: 正本 X-10 は 11_2・11_3・acceptance_extra・test_cli_pipeline・test_api の書き換えを「開発側作業」とするが、handoff 6節は tests/acceptance・test_spec_11_2〜11_8c を保護（変えるのは /st）。作った本人がテストを直すと検証の独立性が崩れる。分類結果は前 handoff 3節（B21 は修正済み）
  - 選択肢: A 保護対象（acceptance 2本・11_2〜11_8c）は /st（spec-tc 新規起動・正本と API の外形だけ渡す）、保護対象外の test_cli_pipeline・test_api だけ implementer（削除 TC は一覧報告）／B X-10 どおり列挙5ファイルは implementer、残り（11_4〜11_8c・acceptance.py）は /st／C 全件 /st
  - AI 推奨: A
  - 未回答の間の扱い: /vf は進める。/st（既存テスト）は回答待ち
  - 状態: 質問済み（セッション7）・未回答（セッション9 冒頭で全文再掲済み）
- 問い（J26・M3/M2 取り込み表示）: 承認済みモックにだけ写っている「対象: 未取り込みの画像 n 件」（取込&作成ダイアログ）と「最終取り込み <日時>」「未取り込み n 件」「フォルダ監視: 稼働中」（取り込みタブ）を実装しますか
  - 背景: recon の DOM 契約突合で欠落（contract_diff_run1/run2・mock_compare #5・6・29・30）。manifest #5・6・29・30 の絵にはあるが、正本の M 表・TC にも改修前アプリ（7aacd05 web/index.html・app.js で grep 0件）にも無く、新しい集計機能になる。「稼働中」はセッション9の突合で追加（正本 grep 0件）。advisor は「黙って落とすのも黙って足すのも範囲逸脱」と判定
  - 選択肢: A 絵で承認済みなので実装する（/im、TC は /st で追加）／B モックの飾りとして正本に「表示しない」と追記（/st）
  - AI 推奨: A（advisor 推奨。絵で承認済み）
  - 未回答の間の扱い: Green は進める。この4項目は Green の判定対象外と報告に明記
  - 状態: 質問済み（セッション9 冒頭で全文提示、「稼働中」は同セッション内で補足）・未回答
### 仮説・未確認
- r2 の不具合候補 (1)〜(7)（gate_state セッション9節）は正本との照合が済んでいない。特に (1) 履歴の詳細でシート行が「[object HTMLDivElement],…」になり「調整する」が出ない（実装バグの疑い大。#41・42 はこのため job_id 付きシートから撮れていない）、(3) 一括印刷が成功した後も held のまま残る（D7 は出力先 pdf。正本 N-85 の期待と照合要）、(4) J4 の折りたたみ
- 履歴詳細の原画像 404 がシード起因か実装起因か未断定
- 取り込みタブの inbox_dir（app.js:147）は sp ではみ出す疑い。r2 では scrollWidth 390 だったので、おそらく問題なし（未断定）
- SKIP 78 と 90 の 10 差の原因、B2（PDF 出力先）、E-26 の TC 強化、前 handoff 4節の残りは未着手

## 5. 却下した案と理由
前の handoff（1_card-master_print-edit_3.md・_2.md・1_card-master_print-edit.md・main_print-edit_28.md）5節の行は全件有効。
| 案 | 却下理由 |
|---|---|
| REGEN=true で spec を全件再生成 | pw-loop の expect revert が新本文に基準 expect を差し込み混成ブロックになる（advisor・pw-loop.sh:99-106） |
| recon を省略して pw-triage に任せる | vf-recon.md:58,104 で省略不可・78件の生成不可を解く材料が recon にしかない |
| 「pw-gen は SKIP 分だけ」を本 spec で行う | pw-gen は SKIP 行を変えない → 試行 spec（PW_SPEC_OUT='#1_main.skip.pw.spec.ts' PW_VF_DIR=.vf/skip）で行う |
| DOM 契約差分だけで 3-3 を通す | 絵との pc/sp 突合が無く sp 未確認は「判定不可」（vf-recon.md:72） |
| 06「画像を選んで取り込む」を /im へ差し戻す | 正本 M3 が「取り込みのみ」ボタンに置き換えた |
| :482「DOM の正本は inject.js」を機能追加の根拠にする | 形（ロケータ）の正本で、範囲は M 表が決める（advisor） |
| 一括結果を「N件中 成功x件・失敗y件」に揃える | 正本 :207「失敗0件なら成功件数のみ」 |
| PDF 作成に上書き確認の注記文を足す | manifest:123 で注記は確認ダイアログの静止画代用 |
| 名刺マスタの名前表示行を消す | N-92 と spec の「（名前なし）」文字ロケータが表示行を要する |
| #38 列優先を /im へ | DOM 座標で M17 どおりと確認済み |
| 全ネイティブ confirm をページ内モーダルに統一 | 承認絵は 03 一括だけ・既存 spec が dialog イベントで待つ |
| 一括ボタン文言を承認絵の「選んだものを印刷（N件）」に | 正本の「一括印刷（N件）」が優先（モックが古い） |

## 6. 触ってはいけないもの
- 前 handoff 6節は全件有効（実機印刷・~/PrintEdit 書込禁止・tests/acceptance 等の期待値・main.md と #1_main.md 凍結（実装判断ログへの追記のみ可）・基準役プロンプトに実装 file:line を書かない・メインは fail_rows/error-context を読まず spec を直接 Edit しない・qkit 本体編集禁止・push なし・`cd … &&` 禁止・rm -rf 禁止・共有ファイル（playwright.config.ts・wt.ts・auth.setup.ts・package.json・test-accounts.local・bt_config.md）変更禁止・.vf/red の expect 固定版を変えない・.vf/seed/main.sh を改名しない・wt 撤去はユーザー許可・tests/ 配下）
- 8781（/mk 土台）・8150（本番）を止めない。既存 .vf/recon/*.png を上書きしない（r2 は .vf/recon/r2/）

## 7. 次の一手
.vf/recon/mock_compare_r2.tsv の差異 47 行を、gate_state セッション9節の既決リストを除いて正本 ai_docs/specs/#1_main.md の grep で分類する（J4・N-85・M13 を照合）→ advisor → 実装バグ分を新しい im_return_r2.tsv にして /im（修正モード・先頭行 MODEL_ESCALATION）→ 該当画面だけ 8795〜8798 で撮り直し → serve 停止 → SKIP 10件の試行 spec → Step 3.5 → pw-all.sh --resume 4 --until 4 → pw-all.sh（bg）→ pw-triage → pw-loop --final。
全体: /vf Green → J25 回答後の /st（既存テスト・E-26）→ pytest 全件 → /sr → main へ取り込み（git 管理外の .vf/e2e/ai_docs の戻し一覧）・次の /go（③テキスト系＋R10-5 濃さ）・周4 の仕様・README 化・11.9 `/st`・実機確認 X-01〜04・/ar Step 0 未消化 67 行（当初の指示 ai_docs/handoff/main_print-edit_3.md:2節）
