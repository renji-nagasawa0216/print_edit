# #1_card-master 引き継ぎ（2026-11-20）

## 1. 環境
- 作業ディレクトリ: `/Users/renji/Projects/private/print_edit/.worktrees/issue1`（main の作業ツリー内の wt。起動ディレクトリからは相対 `cd .worktrees/issue1` を単独で）
- ブランチ: `#1_card-master`（ベース main 7aacd05。番号 1 は名目上）
- 前の handoff: `/Users/renji/Projects/private/print_edit/.worktrees/issue1/ai_docs/handoff/1_card-master_print-edit.md`（2・5節以外の古い事実はここ。3節に無いことはこのファイルから辿って grep する）
- 用途: `print-edit`
- 差分: 8 files changed, +1535/−354 ＋ ?? src/print_edit/arrange.py（未コミット）。ベースURLは helper が TC ごとに一時 home・空きポートで serve。DB は <home>/db.sqlite3
- 個人プロジェクト（Python 3.12・uv・FastAPI・SQLite・素の JS。ログインなし）。remote なし。ユーザー本番は port 8150（`~/PrintEdit`）

## 2. ユーザーの指示（逐語）
- 前の handoff 2節は全件有効（`1_card-master_print-edit.md` 2節 → さらに `main_print-edit_28.md` 2節。/go 起動「このpj要件を改修したい。割と大幅な回収になるので、先に要件定義して実装してもらおうかと思います。」・「mainの方はもう面倒なのでコミットしてしまってください。…」「ただwt作成する必要もないので、今回はbで進めて問題ありません」・J10・J13・R10-5「ではa,bどちらもで。」・J18〜J21「ok, 良いです」・J22/J23「私は指示出ししていないですね、judgeは推奨で問題ありません」・「すいません、advisorに委ねる絶対条件ってどこにありますか？それ削除して良いです」ほか）
- pw-gen 経路の judge への回答: 「A: wt を作る」
- wt の番号・/im も wt で行うかの確認への回答: 「任せます」→ 番号 1・/im も wt・最後に main へ取り込み
- 今回のセッションでユーザー発言なし（auto-relay 1/5 のみ）

## 3. 確定した事実
- 既存 pytest fail 484 の分類（investigate、詳細 `/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/457faae9-3dfb-4718-b850-3291a1170792/scratchpad/classify/cls2.tsv`、列 分類/ファイル/nodeid/エラー/理由）: S42 / R138 / D235 / B21 / P45 / 不明3 = 484。P は 7aacd05 を git archive で流し 41件実測＋4件（N41/N42/N61/C29、基準 0f713ff）は推論。D/R/S は機械分類で全件目視なし。不明3 = test_spec_11_7 の test_new_sheet_pdf_has_white_edge・test_saved_pdf_and_cards_unchanged_after_setting_change・test_cards_source_layout_capacity_same_as_zero。X-13 描画テストは fail に含むが全て P（7aacd05 と wt で impose の出力 PDF は画像・コンテンツ同一、差は末尾メタデータ 66 byte）
- advisor 指摘（分類の扱い）: /st には正本と nodeid だけ渡し分類ラベルは渡さない（書き換えてよい前提が付き B が期待値ごと消える）。R 削除は /st が正本の根拠行を出したものだけ。N47 per_scan は D・11_4 Origin N02/N05 は D 寄り
- B 21件（acceptance A7_capacity/A8_* × gap_10_5/paper_a5/paper_letter/tie_square200）修正済み（/im 修正モード、implementer opus、`MODEL_ESCALATION: 修正モード` 行が hook に必要）: src/print_edit/home.py（+95/−6）。`_read_global` 1か所で外部 --config（`external_config`）を判定し、旧形式はメモリ変換（`_convert_legacy`）して get_preset/load_settings で DB「既定」より優先。ファイル・.bak・DB は書かない。home 自身の config.json 移行（R18）は現状維持
- 実装判断ログ ai_docs/specs/#1_impl_decisions.md:13 に1行追記（implementer の Edit は independence hook が拒否 → /im 手順どおりメインが追記。verify-base denials の1件はこれ）
- 範囲外の残り: serve --config 時の API 保存が外部ファイルを上書き（src/print_edit/api/app.py:132,533）・app.py:528 は変換値でなく DB「既定」を使う・home.py:139 save_settings
- fixture 復元: tests/acceptance/fixtures/configs/ の4件（gitignore の生成物）を .bak 内容で戻した。退避（.bak と移行後版）は `/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/457faae9-3dfb-4718-b850-3291a1170792/scratchpad/bak_retreat1/`
- 検証: A7/A8 を2回連続で 56 passed・configs sha 不変・.bak 新規0。acceptance 全体 8 failed / 120 passed / 1 skipped（残8 = test_acceptance_extra の R6・D1・S1、分類どおり）。横断照合 grep をメインで再実行し一致（im-check.sh cross は Python を拾わない）
- /vf Green 準備: Step 0 済（worktree・verify_base=7aacd05・preflight 3か所 OK）。.vf/red/#1_main.pw.spec.ts あり・.vf/recon/selectors.tsv なし
- test-data 用に現在の定義を `.vf/pw/impl_shapes/` に出力（一時 home で prepare＋TestClient POST /api/pdf）: schema_impl.sql・preset_default_data.json・sheet_row_example.tsv（snapshot は `{"v":1,"settings":…,"items":[{card_id,count}]}`、/api/pdf の sheet は job_id NULL・status created）・config_json_example.json・api_routes.txt・arrange_values.txt（order row/col）
- test-data（2往復）: 前提データ 172件すべて PENDING なしで投入可（`grep -c PENDING .vf/seed/main.sh` = 0）。新規 .vf/seed/data/mk_sets.py、main.sh は sets() で呼ぶ、SEED_ORDER_COL 既定 col。代表 TC（N-01・N-19・N-27・N-05・N-14・N-18・N-54・N-75・N-85・N-99・B-09・P-01・P-02・N-03・N-82・B-18・N-101）を一時 home で rc=0・件数確認。拒否アクセスなし
- TestClient で Origin: http://testserver を付けると 403（別サイト判定）。付けなければ通る

## 4. 未確定・仮説
### ユーザーへの確認事項
- 問い（J24・M28 印刷待ち）: 印刷待ちが0件のとき、一括操作のバー（全選択・一括印刷・一括破棄）を出しますか
  - 背景: tc-judge（セッション6）が B-14 を「弱い」と判定。正本 :225 の0件列にバーの記述が無く、文言だけでは改修前と見分けられない
  - 選択肢: A 0件ではバーを出さない（B-14 は Red を求めないデグレ確認 TC と明記）／B バーを出し一括印刷・一括破棄を disabled（B-14 に「disabled のまま」を足して Red にできる）
  - AI 推奨: A（承認済み mock 03 に0件の絵が無く、空の一覧に操作バーを出す利点が小さい）
  - 未回答の間の扱い: implementer は A を仮置き済み。/vf は止めない
  - 状態: 質問済み（セッション6）・未回答（今回セッション冒頭で全文再掲済み）
- 問い（J25・M15/M5/M24 既存テスト）: 改修で落ちる既存テスト 484 件を誰が直しますか
  - 背景: 正本 X-10 は 11_2・11_3・acceptance_extra・test_cli_pipeline・test_api の書き換えを「開発側作業」とするが、handoff 6節は tests/acceptance・test_spec_11_2〜11_8c を保護（変えるのは /st）。作った本人がテストを直すと検証の独立性が崩れる。分類結果は3節（B21 は修正済み）
  - 選択肢: A 保護対象（acceptance 2本・11_2〜11_8c）は /st（spec-tc 新規起動・正本と API の外形だけ渡す）、保護対象外の test_cli_pipeline・test_api だけ implementer（削除 TC は一覧報告）／B X-10 どおり列挙5ファイルは implementer、残り（11_4〜11_8c・acceptance.py）は /st／C 全件 /st
  - AI 推奨: A
  - 未回答の間の扱い: /vf は進める。/st（既存テスト）は回答待ち
  - 状態: 質問済み（セッション7）・未回答（今回セッション冒頭で全文再掲済み）
- E-26 の TC 強化（前提 D3a・lp＋送信記録 stub・POST /api/jobs/JA/reprint・2xx でない＋送信0件＋S1〜S8 不変）は業務判断不要。/st（spec-tc 新規）で直す。未着手
### 仮説・未確認
- /vf の経路が2つの指示で食い違う: vf-standard.md Step 1 は「.vf/red あり・selectors.tsv なし → 初回ルート（vf-smoke Step 2 → vf-recon Step 3 で recon）→ pw-all.sh --regen を REGEN=true（expect 固定）」。前 handoff/gate_state セッション6（advisor）は「REGEN推奨は再生成しない。Red の spec＋pw-triage・pw-gen は SKIP 分のみ」。recon・smoke は QuartettCMS（ログイン・Docker）前提の記述が多い。次セッションで advisor に判定させる
- test-data 未確定2件: sheets.snapshot「あり」の中身（既定値で埋めた。E-40 S3 の復元値は実装既定と区別不能）・created_at（2026-11-05T12:00:NN 連番）と pdf 実体（空1ページ）
- helper 追加（DB 直読み・serve 再起動・偽 lp 記録読み）で生成不可 78 のうち約15件が生成可能（pw-gen 申告）
- 前 handoff 4節の残り（旧 11.8/11.8c DOM TC 判定記録なし・E-12 cards_per_sheet NULL・10スロットプレビュー API・fontTools 段階③）未着手

## 5. 却下した案と理由
前の handoff（1_card-master_print-edit.md・main_print-edit_28.md）5節の行は全件有効。
| 案 | 却下理由 |
|---|---|
| 外部 --config を「メモリ変換だけ」で直す | 面付けは DB「既定」から取るため1回目から容量10になる（advisor #2） |
| 外部 --config を DB の「既定」に書く | 既定値がある home では --config の layout が黙って捨てられる |
| make_fixtures.py を全部再実行して fixture を戻す | images・cards・expected.json まで作り直される（.bak から4件だけ戻した） |
| /st に分類ラベル（S/R/D）を渡す | 書き換えてよい前提が付き B が期待値ごと消える（advisor #7） |
| 古い .bak を削除 | 削除禁止。退避先へ mv |

## 6. 触ってはいけないもの
- 前 handoff 6節は全件有効（実機印刷・~/PrintEdit 書込禁止・tests/acceptance 等の期待値・main.md と #1_main.md 凍結・基準役プロンプトに実装 file:line を書かない・メインは fail_rows/error-context を読まず spec を直接 Edit しない・qkit 本体編集禁止・push なし・`cd … &&` 禁止・rm -rf 禁止・共有ファイル（playwright.config.ts・wt.ts・auth.setup.ts・package.json・test-accounts.local・bt_config.md）変更禁止・.vf/red の expect 固定版を変えない・.vf/seed/main.sh を改名しない・wt 撤去はユーザー許可）
- tests/ 配下（fixture 4件の復元は済。以後触らない）

## 7. 次の一手
/vf Green の続き: ~/.claude/agent-parts/vf-standard.md Step 1 と vf-step0.md を Read し、4節「/vf の経路の食い違い」を advisor に判定させて経路を決め → （必要なら helper 追加）→ pw-all.sh（run_in_background、出力 .vf/pw/<名前>.out）→ pw-triage → pw-loop.sh --final → ★人間ゲート（RTM・172件照合）。
全体: /vf Green → J25 回答後の /st（既存テスト・E-26）→ pytest 全件 → /sr → main へ取り込み（git 管理外の .vf/e2e/ai_docs の戻し一覧）・次の /go（③テキスト系＋R10-5 濃さ）・周4 の仕様・README 化・11.9 `/st`・実機確認 X-01〜04・/ar Step 0 未消化 67 行（当初の指示 ai_docs/handoff/main_print-edit_3.md:2節）
