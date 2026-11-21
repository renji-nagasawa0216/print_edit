# #1_card-master 引き継ぎ 5（2026-11-21）

## 1. 環境
- 作業ディレクトリ: `/Users/renji/Projects/private/print_edit/.worktrees/issue1`（main の作業ツリー内の wt）
- ブランチ: `#1_card-master`（ベース main 7aacd05）
- 前の handoff: `ai_docs/handoff/1_card-master_print-edit_4.md`（2・5節以外の古い事実はここ）
- 用途: `print-edit`（名刺スキャン→A4 面付け→印刷の Mac 用ツール。Python 3.12・uv・FastAPI・SQLite・素の JS）
- remote: `print_edit`（https://github.com/renji0216/print_edit）。push 済みの範囲は本 handoff の commit までで、それ以降の commit は push 時に確認する
- 作業状態の詳細記録: `ai_docs/handoff/1_card-master_print-edit_5_gate_state.md`（セッション9・10 の時系列。原本は scratchpad の st2/gate_state.md）

## 2. ユーザーの指示（逐語）
- 「一旦停止して良いです、使用量がえげつない」（r3 撮り直しの verifier を停止）
- 「テスト関係とかgitignoreに設定されているものでnodemoduleのようなものではないもの全てpush対象としたいです」
- 「2は省き、1入れましょう。それでpushお願いします」（2=.vf/、3=__pycache__ 等の生成物。1=e2e の認証関連を含む除外対象）
- 「ai_docsも含めたいです、未着手とかあと今このセッションで何をやっていたかというところまで含めてお願いします。和ツィが明示的に許可するのでpushしておkです」（push 権限の明示許可。直前に auto mode の分類器が push を機密情報の観点で拒否したが、ユーザーが許可した）
- 前 handoff 2節の指示は全件有効（`1_card-master_print-edit_4.md` 2節）

## 3. 確定した事実
- commit `537e797`（ローカル commit 時点）: `.gitignore` 除外対象のうち e2e/ 直下 10 件・tests/acceptance/ 76 件（fixtures・extra_fixtures）を `git add -f`。`.gitignore` は未変更。`.vf/`・`__pycache__`・`.pytest_cache`・`.DS_Store`・`e2e/node_modules`・`e2e/test-results` 等は除外
- e2e/accounts/・e2e/.auth/ は実在しない
- 撮影用 home（scratchpad recon2/{d1,d2,d3,d7}）の全ジョブに source.png を生成した（撮影時の原画像 404 の解消。生成は cards/*.png を白地に並べたもの＝撮影用の代用画像）
- /vf 3-3 突合の経緯:
  - 1回目 `.vf/recon/mock_compare.tsv`（after 32件。一致2・差異26・判定不可4）→ /im 15行（`.vf/recon/im_return.tsv`）→ 修正済み
  - 2回目 `.vf/recon/mock_compare_r2.tsv`（67行。差異47）→ 分類 `.vf/recon/r2_classify.tsv`（既決22・視覚差10・実装バグ6・データ起因6・モック古い3）→ advisor「修正してから続行」9件反映 → `.vf/recon/im_return_r2.tsv`（5行: B1・B6・B4・B5・B8）→ /im 修正 → 検証済み（後述）
- /im（r2）の修正内容（app.js・style.css のみ）:
  - B1 履歴詳細のシート行が「[object HTMLDivElement]」になる不具合（app.js:257 の配列直渡し→展開）
  - B6 PDF 作成の補正・面付けを fieldset>legend＋details（summary「項目を表示」・既定閉。仮文言）に組み替え（app.js:856-861 の PDF 作成側だけ。設定作成と共通 presetFields は不変）
  - B4 登録待ちカードを名刺マスタと共通の `.ccard`/`.cgrid` 横並びに（style.css）
  - B5 名刺マスタの選択強調を灰背景＋濃い枠（style.css:31）
  - B8 PDF 作成 sp の使う名刺行: 名前を1行目・枚数と削除を2行目（style.css 800px 以下の規則）
  - 検証: im-check cross 全21件（変更行のみ）・quartett-lint 出力0・`node --check` OK。画面・e2e は未実行
- 実装判断ログ（`ai_docs/specs/#1_main.md` 末尾）に r2 の追記済み（summary 文言「項目を表示」は仮）
- 原画像 404 はシードの問題（撮影 home の jobs/*/source.* が無かった）。履歴詳細の #0 起点はシード D2o が idx を 0 始まりで置くため（実データの idx は detect.py:163 で 1 始まり）

## 4. 未確定・仮説
### ユーザーへの確認事項（未回答。全文は回答者に再掲が必要）
- J24（印刷待ち0件の一括バー）: A 0件ではバーを出さない（AI 推奨・implementer は A で仮置き）／B バーを出し disabled
- J25（改修で落ちる既存テスト 484件の扱い）: A 保護対象（acceptance 2本・test_spec_11_2〜11_8c）は /st・保護対象外の test_cli_pipeline・test_api だけ implementer（AI 推奨）／B X-10 どおり5ファイルは implementer・残りは /st／C 全件 /st
- J26（モックにだけあるもの）: 取り込みタブの「フォルダ監視: 稼働中」「最終取り込み」「未取り込み n 件」、取込&作成ダイアログの「対象: 未取り込みの画像 n 件」を A 実装（/im・TC は /st で追加。AI 推奨）／B 正本に「表示しない」と追記
- 正本の欠け: manifest:155 の J4（PDF 作成の補正・面付けを折りたたみ）は正本本文に記述がない。TC も無い。実装は済みだが正本へ追記が要る（業務判断。/st の対象）

### 未着手（順番どおり）
1. r3 撮り直し: 02 履歴詳細（JA から開く）・06 取り込み・07 名刺マスタ・08 PDF 作成（通常・「調整から開く」）の pc/sp。verifier を新規起動（前回は停止）。結果は `.vf/recon/r3/`・`.vf/recon/mock_compare_r3.tsv`
2. SKIP 10件の試行 spec（PW_SPEC_OUT='#1_main.skip.pw.spec.ts' PW_VF_DIR=.vf/skip）
3. Step 3.5（流用元の検収）
4. `pw-all.sh --resume 4 --until 4` → `pw-all.sh`（bg）→ `pw-triage` → `pw-loop --final`
5. pytest 全件（Red/Green の件数を別記録）
6. `/st`（既存テストの扱い J25 の回答後）・E-26 の TC 強化
7. `/sr` → main へ取り込み（git 管理外の `.vf/`・`e2e/`・`ai_docs/` の戻し一覧）
8. 撮影用サーバー 8795〜8798 は稼働中（停止は未実施。8781 は /mk 土台、8150 は本番のため触らない）

### 仮説・未確認
- 履歴詳細のカード番号 #idx は実データでは 1 始まりのため、撮影上の差はシード由来と判断（未実画面確認）
- sp の使う名刺行の 2 行化は `:has()` 対応ブラウザ前提（古いブラウザでは wrap のみ）
- B6 の折りたたみ文言「項目を表示」は仮
- 旧 SKIP の数の食い違い（メモ 78 / 実数 90 のうち test( は 87）は原因未確認
- 旧正本 11.8（skip 24）・11.8c（skip 7）の DOM TC は判定記録なし（範囲外）

## 5. 却下した案と理由
| 案 | 却下理由 |
|---|---|
| r2 の B2（#0 起点）を /im で直す | 実データは 1 始まり（detect.py:163）。シードの 0 始まりが原因 |
| B7（拡大ボタン要否）・B9（拡大の赤破線）を /im で直す | 赤破線は改修前からの既存表示。M18 の範囲内で低優先のため差異として報告に残す |
| 補正・面付けを presetFields 自体で折りたたむ | 設定作成画面（N-35 が group「補正」「面付け」を確認）まで閉じてしまうため、PDF 作成側だけ |
| 一括印刷後の held 残留を不具合として直す | 正本 N-85「印刷待ちのまま」「送信なし（出力先 pdf）」と一致 |
| ファイル単位の verifier 撮影を並列で継続 | 使用量が大きいとユーザーが停止指示（r3 撮り直しを途中停止） |
| push を Bash の既定ルールのまま実行 | 機密情報の観点で分類器が拒否。ユーザーが明示許可（ai_docs・認証関連を含めた push） |

## 6. 触ってはいけないもの
- 実機への印刷・送信（`lp`・`nc`）と `~/PrintEdit` への書込み（ユーザーが行う。テストは一時ディレクトリで）
- `tests/acceptance/`・`test_spec_11_2〜11_8c` の期待値をメインが変えない（変えるのは `/st`）
- `ai_docs/specs/main.md` と `ai_docs/specs/#1_main.md` は凍結（実装判断ログへの追記のみ可）
- 基準役（spec-tc・tc-judge・test-data・pw-gen・verifier）へ実装の file:line・handoff 本体を書かない
- メインは fail_rows.tsv・error-context.md を読まず、spec を直接 Edit しない（pw-triage へ）
- 共有ファイル（playwright.config.ts・wt.ts・auth.setup.ts・package.json・test-accounts.local・bt_config.md）は pw-red の後に変えない
- `.vf/red` の expect 固定版を変えない。`.vf/seed/main.sh` を改名しない
- qkit 本体（`~/claude-plugins/qkit/`）は編集しない
- `cd … &&` をつながない。`rm -rf` を Bash に渡さない。BSD コマンドに GNU オプションを使わない
- 認証関連ファイル（test-accounts.local・bt_config.md）の値を会話や報告に転記しない
