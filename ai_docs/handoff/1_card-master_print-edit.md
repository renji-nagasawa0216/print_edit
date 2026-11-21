# #1_card-master 引き継ぎ（2026-11-20）

## 1. 環境
- 作業ディレクトリ: `/Users/renji/Projects/private/print_edit/.worktrees/issue1`（main の作業ツリー内に置いた wt。`.worktrees/` は .git/info/exclude 済み）
- ブランチ: `#1_card-master`（ベース main 7aacd05。番号 1 は remote が無いための名目上の番号）
- 前の handoff: `/Users/renji/Projects/private/print_edit/ai_docs/handoff/main_print-edit_28.md`（2・5節以外の古い事実はここ。3節に無いことはこのファイルから辿って grep する）
- 用途: `print-edit`
- git status: `?? ai_docs/` のみ（.vf/・e2e/ は exclude）。実装差分なし（HEAD 7aacd05）
- 個人プロジェクト（Python 3.12・uv・FastAPI・SQLite・素の JS。ログインなし）。remote なし。ユーザー本番は port 8150（`~/PrintEdit`）

## 2. ユーザーの指示（逐語）
- 前の handoff 2節は全件有効（`main_print-edit_28.md` 2節。/go 起動「このpj要件を改修したい。割と大幅な回収になるので、先に要件定義して実装してもらおうかと思います。」・「mainの方はもう面倒なのでコミットしてしまってください。…」「ただwt作成する必要もないので、今回はbで進めて問題ありません」・J10・J13・R10-5「ではa,bどちらもで。」・J18〜J21「ok, 良いです」・J22/J23「私は指示出ししていないですね、judgeは推奨で問題ありません」・「すいません、advisorに委ねる絶対条件ってどこにありますか？それ削除して良いです」（確認事項はユーザーに直接聞く）ほか）
- 今回 pw-gen 経路の judge への回答: 「A: wt を作る」（wt issue<N>・ブランチ #<N>_… を 7aacd05 から作り Red・Green を回す）
- wt の番号・/im も wt で行うかの確認への回答: 「任せます」→ 番号 1・/im も wt・最後に main へ取り込み、と決めた

## 3. 確定した事実
- pw-guard（~/.claude/hooks/pw-guard.sh:120-129,370）は wt 名 issue<N>＋ブランチ #<N>_ が揃わないと pw-gen の書き込みを全拒否。roles.tsv:21 は `tests/#{issue}_*.pw.spec.ts` のみ allow。main での pw-gen は 0 バイトで終了
- wt 作成: `git worktree add -b '#1_card-master' .worktrees/issue1 7aacd05`。pw-env で ISSUE=1・SPEC_PATH=ai_docs/specs/#1_main.md・TEST_FILE=e2e/tests/#1_main.pw.spec.ts
- wt へ写したもの（git 管理外）: ai_docs/specs/main.md→#1_main.md（cmp 同一）・main_req.tsv→#1_req.tsv・ai_docs/documents/main/・.vf/{seed,pytest,fakebin_main,pw/schema_7aacd05.tsv}・e2e（node_modules 等除く）。uv sync・pw-bootstrap --fix 全 OK・verify-base set 7aacd05
- .vf/pw/schema_7aacd05.tsv: 7aacd05 db.py の4表31列（DB に CHECK/ENUM 無し→ options 空）
- test-data: 前提データ持ち TC 172・実投入 13（D4 系。mk_d4.py）・PENDING 159（宣言ファイル .vf/seed/data/*.tsv）・未確定 8件（API パス U-15/U-16・移行後の列名/キー名・D3 スナップショット値・N-75 の PDF 実体）。assign.tsv: pw 161 / pytest 6 / both 5 / 自動実行不可 15
- test-data の絶対パス埋め込み（conftest.py:16・main.sh:184）を test-data に直させた（__file__ / スクリプト位置基準）。残り 0件
- pytest Red（wt、.vf/pytest/red.txt）: fail 10 / pass 1（N-94）/ skip 15 / error 0
- pw-gen（wt）: 生成 87 / 生成不可 78。pw-check NG 0・WARN 0（test 87・skip 100・gap 0）。denials 0件
- helper 修正（メイン、e2e/tests/helpers/home.ts）: stop() が SIGTERM 後に exit を待たず、同ワーカーの次 TC が同ポートで起動失敗→終了処理中の旧サーバに waitReady が成功→ERR_CONNECTION_REFUSED（1回目 B-16・2回目 E-28 が「環境」）。stop を async で exit 待ち（最大10s）・alive() に signalCode・応答後 300ms で自プロセス生存確認。helper は .vf/shared.sha の対象外
- pw-red 3回目（.vf/pw/red.out。1・2回目は red_run1/2.out）: red_check_完了=はい・実行 88（setup 含む）・期待不一致 4（N-01・N-02・N-43・N-16）・要素未検出 80・不明 1（E-14: home に config.json が無い ENOENT）・既にpass 2（E-26・B-14）・環境 0・REGEN推奨=はい・壁 251s
- 合計照合: 172 = 実行 94（pw 87 + pytest のみ 7: N-94,N-93,E-03,N-90,N-91,E-25,P-02）+ 未テスト 78。94 のうち Red 92・pass のみ 2（B-14・N-94）
- 確定件数（advisor セッション7で再点検・172照合済み）: Red（データ非依存）12（pw: 期待不一致4 N-01・N-02・N-16・N-43＋要素未検出のうち D4 系8。pytest の N-16・N-43 は同じ TC なので重ねて数えない）／シード待ち 79（pw 73＝要素未検出80−D4 8＋E-14、pytest のみ6: N-93・E-03・N-90・N-91・E-25・P-02）／既にpass 3（E-26・B-14・N-94。E-26・B-14 はシード PENDING のままの pass、N-94 は移行が起きないための空振りの可能性 → いずれも判定材料にせず Green 報告で明記）／未テスト 78。合計 172
- （旧・誤り。合計 179 になる）上2行の数え直し（advisor、セッション6）: Red（データあり）約12（pw 12・pytest 2: N-16・N-43）／Red（シード待ち）pw 77・pytest 8／既にpass 2／E-14 はシード待ちに再分類／未テスト 78。シード待ち 85件は旧コードで Red 確認不能（Green 報告へ引き継ぐ）。詳細 gate_state「セッション6」
- /im（セッション7）: implementer（sonnet）が M1〜M32 を実装済み・未コミット（8ファイル変更＋新規 src/print_edit/arrange.py、+1514/−354）。/clear 前起動の implementer と重複起動し、後発（停止済み）が arrange.py を上書き→先発が書き直し済み。判断・ルート・スキーマは ai_docs/specs/#1_impl_decisions.md（正本凍結のため別置き。main 取り込み時に /st が移す）
- 検収: 流用元（change_reg←claim_sheet）OK・cross 再実行 card-status 全16（未変更2行 app.js:267-268 はシート status で対象外）・old-settings 全1・job-reprint 全1・quartett-lint 出力なし・ruff 未導入
- 既存 pytest: 484 failed / 333 passed / 27 skipped。tests/ の差分 0。test_core whiten は 7aacd05 でも fail（範囲外）。advisor: implementer に保護テストを触らせない・未分類約48件は investigate で分類（実行中）・X-13 の描画テストが fail に含まれるか要確認・順序は 分類 → /vf と /st 並行 → pytest 全件 → /sr
- main 側にも旧成果物が残る: main の .vf/pw/tc.tsv・e2e/tests/main.pw.spec.ts（骨格のみ）・.vf/seed・.vf/pytest（絶対パス修正前の版）

## 4. 未確定・仮説
### ユーザーへの確認事項
- 問い: 実装後の Green 確認（pw-loop）で、書込系 TC 58 件をどう扱いますか
  - 背景: qkit の pw-loop はメインワークツリーでは書込系 TC を除外（--grep-invert）し、シードも流さない（pw-loop.sh:67-71,127）。今回 wt を作ったので、wt で Green を回せば A 相当になる見込み
  - 選択肢: A wt を作って Green を回す（済）／B 58 件を「未検証」のまま報告／C pw-run --all を直接使い全件流す
  - 未回答の間の扱い: Green に入る前に、pw-loop.sh:67-71 が wt で書込系を含むことを確認する。含むならこの問いは不要として報告のみ（A で解決）
  - 状態: 不要（A で解決。pw-loop.sh:66-70 は IS_WT=false のときだけ除外し、この wt は IS_WT=true）。報告のみ
- 問い（J24・M28 印刷待ち）: 印刷待ちが0件のとき、一括操作のバー（全選択・一括印刷・一括破棄）を出しますか
  - 背景: tc-judge（セッション6）が B-14 を「弱い」と判定。正本 :225 の0件列にバーの記述が無く、文言だけでは改修前と見分けられない
  - 選択肢: A 0件ではバーを出さない（B-14 は Red を求めないデグレ確認 TC と明記）／B バーを出し一括印刷・一括破棄を disabled（B-14 に「disabled のまま」を足して Red にできる）
  - AI 推奨: A（承認済み mock 03 に0件の絵が無く、空の一覧に操作バーを出す利点が小さい）
  - 状態: 質問済み（セッション6）・未回答
- 問い（J25・M15/M5/M24 既存テスト）: 改修で落ちる既存テスト 484 件を誰が直しますか
  - 背景: 正本 X-10 は 11_2・11_3・acceptance_extra・test_cli_pipeline・test_api の書き換えを「開発側作業」とするが、handoff 6節は tests/acceptance・test_spec_11_2〜11_8c を保護（変えるのは /st）。作った本人がテストを直すと検証の独立性が崩れる
  - 選択肢: A 保護対象（acceptance 2本・11_2〜11_8c）は /st（spec-tc 新規起動・正本と API の外形だけ渡す）、保護対象外の test_cli_pipeline・test_api だけ implementer（削除 TC は一覧報告）／B X-10 どおり列挙5ファイルは implementer、残り（11_4〜11_8c・acceptance.py）は /st／C 全件 /st
  - AI 推奨: A
  - 状態: 質問済み（セッション7）・未回答。/vf はこの回答を待たずに進めてよい（advisor）
- E-26 の TC 強化（tc-judge 案: 前提 D3a・出力先 lp＋送信記録 stub・POST /api/jobs/JA/reprint・2xx でない＋送信0件＋S1〜S8 状態不変）は業務判断不要。正本凍結のため /st（spec-tc 新規起動）で TC を直す。未着手
### 仮説・未確認
- 生成不可 78 件の理由: 履歴のシート行の識別・確認ダイアログ形式（native/DOM）・保存方法の入力形式・API パスが正本/DOM 契約に無い。helper 追加（DB 直読み・serve 再起動・偽 lp 記録読み）で約15件生成可能（pw-gen 申告）
- pw-gen の推測リスク: ロケータは inject.js 由来で実 DOM と不一致の可能性・「（名前なし）」を正本の文字表示と仮定（実装がモック placeholder 寄りなら N-19〜21・N-92・E-06・B-01・B-02 が落ちる）・dialog は page.on('dialog') 前提（DOM なら N-29・N-34・E-01・E-22）
- 全 TC が生成不可の describe（S7・P1・S1・H2・S3・JB・S4）は pw-check で NG にならなかった
- 前 handoff 4節の残り（旧 11.8/11.8c DOM TC 判定記録なし・E-12 cards_per_sheet NULL・10スロットプレビュー API・fontTools 段階③）は未着手

## 5. 却下した案と理由
前の handoff（main_print-edit_28.md）5節の行は全件有効。
| 案 | 却下理由 |
|---|---|
| pw-guard を改修して main で pw-gen（B） | ユーザーが A（wt）を選択 |
| pytest だけで Red（C） | UI の TC 約118件が Red の分母から外れる（advisor 既却下） |
| wt を作業ディレクトリ外（print_edit_wt/issue1）に置く | セッション cwd を移せず pw-guard が main 扱いで再拒否（advisor #1） |
| /wt -c で作る | QuartettCMS 用で Docker・DB 前提 |
| 環境1件を無視して Red 完了扱い | red_check_完了=いいえ。原因は helper の停止待ち不足で再現性あり |
| メインが conftest の絶対パスを直す | テスト入力は基準役の成果物（test-data に戻した） |

## 6. 触ってはいけないもの
- 前 handoff 6節は全件有効（実機印刷・~/PrintEdit への書込禁止・tests/acceptance 等の期待値・main.md 凍結・基準役プロンプトに実装 file:line を書かない・メインは fail_rows/error-context を読まず spec を直接 Edit しない・qkit 本体編集禁止・push なし・`cd … &&` 禁止・rm -rf 禁止）
- wt の ai_docs/specs/#1_main.md も凍結（main.md の写し）
- 共有ファイル（playwright.config.ts・wt.ts・auth.setup.ts・package.json・test-accounts.local・bt_config.md。.vf/shared.sha 記録済み）は変えない（pw-loop exit 3）
- .vf/red/ の expect 固定版を変えない
- .vf/seed/main.sh を #1_main.sh に改名しない（pw-env.sh:80 で SEED_FILE が立ち pw-loop が引数なしで呼んで exit 2）
- wt の撤去は手動 `git worktree remove` でユーザー許可を取ってから

## 7. 次の一手
investigate（既存テスト 484 件の分類 S/R/D/B/P。scratchpad 0ec27344…/scratchpad/ 配下に pytest_all.txt）の結果待ち → B（実装バグ候補）があれば `/im` 修正モード（implementer 新規・opus）→ `/vf`（Green: test-data で宣言→実スキーマ写し・helper 追加・pw-gen は SKIP 分のみ・pw-loop）と J25 回答後の `/st`（既存テスト）を並行 → pytest 全件 → /sr。
全体: 今回の /go（①②）の /im → Green（pw-loop、4節の確認）→ /sr → main へ取り込み（git 管理外の .vf/e2e/ai_docs の戻し一覧を作る）・次の /go（③テキスト系＋R10-5 濃さ）・周4 の仕様・README 化・11.9 `/st`・実機確認 X-01〜04・/ar Step 0 未消化 67 行（当初の指示 ai_docs/handoff/main_print-edit_3.md:2節）
