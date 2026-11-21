# #1_card-master 引き継ぎ（2026-11-20）

## 1. 環境
- 作業ディレクトリ: `/Users/renji/Projects/private/print_edit/.worktrees/issue1`（main の作業ツリー内の wt。起動ディレクトリからは相対 `cd .worktrees/issue1` を単独で）
- ブランチ: `#1_card-master`（ベース main 7aacd05。番号 1 は名目上）
- 前の handoff: `/Users/renji/Projects/private/print_edit/.worktrees/issue1/ai_docs/handoff/1_card-master_print-edit_2.md`（2・5節以外の古い事実はここ。3節に無いことはこのファイルから辿って grep する）
- 用途: `print-edit`
- 差分: 8 files changed, +1535/−354 ＋ ?? src/print_edit/arrange.py（未コミット）。Green の baseURL は helper が TC ごとに一時 home・空きポート（8900〜）で serve。DB は <home>/db.sqlite3
- recon 用 serve（このセッションで起動・稼働中のはず）: 8791（D3+inbox, scratchpad recon_home1）・8792（D1・個別破棄で 4→2 件に壊れた）・8793（D2）・8794（D7・一括印刷で消費済み）。scratchpad=/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/27c0f746-9223-4ade-ad85-0e1c7bd0bffb/scratchpad。8781 は /mk の土台（触らない）
- 個人プロジェクト（Python 3.12・uv・FastAPI・SQLite・素の JS。ログインなし）。remote なし。ユーザー本番は port 8150（`~/PrintEdit`）

## 2. ユーザーの指示（逐語）
- 前の handoff 2節は全件有効（`1_card-master_print-edit_2.md` 2節 → `1_card-master_print-edit.md` 2節 → `main_print-edit_28.md` 2節。/go 起動「このpj要件を改修したい。割と大幅な回収になるので、先に要件定義して実装してもらおうかと思います。」・「mainの方はもう面倒なのでコミットしてしまってください。…」「ただwt作成する必要もないので、今回はbで進めて問題ありません」・J10・J13・R10-5「ではa,bどちらもで。」・J18〜J21「ok, 良いです」・J22/J23「私は指示出ししていないですね、judgeは推奨で問題ありません」・「すいません、advisorに委ねる絶対条件ってどこにありますか？それ削除して良いです」ほか）
- pw-gen 経路の judge への回答: 「A: wt を作る」
- wt の番号・/im も wt で行うかの確認への回答: 「任せます」→ 番号 1・/im も wt・最後に main へ取り込み
- 今回のセッションでユーザー発言なし（auto-relay 1/5 のみ）

## 3. 確定した事実
- 作業状態の正本: `/private/tmp/claude-501/-Users-renji-Projects-private-print-edit/c92d8efd-1326-4d2d-b628-02740df6da4e/scratchpad/st2/gate_state.md`「## /vf Green（セッション8・wt issue1）」（必ず全文 Read。advisor 2回の判定・分類・次手順の詳細はここ）
- advisor（経路）: 折衷。recon（契約検証・selectors.tsv）は省略不可で実施済み。smoke は省略（ログイン無し・recon で代替）と報告に残す。Step 4-5 は REGEN 全件再生成せず Red の spec＋pw-triage（qkit SKILL.md:34）。pw-all.sh を引数なしで打つと ROUTE=recon+gen で spec を上書きする（pw-env.sh:104）→ selectors.tsv がある今は要確認、無ければ --resume 4 必須
- recon run1（前提 D3+inbox）: png 26・selectors.tsv 161 行（未取得 35）・errors 0・契約差分 24 行（.vf/recon/contract_diff_run1.tsv）。run2（06=D1・08=D2）: selectors 約50行追記・.vf/recon/contract_diff_run2.tsv 20 行。追加撮影 7 枚（03 選択 sp・結果 pc/sp、04 sp、08 sp・拡大 sp・列優先 sp）ok
- advisor（3-3）判定「修正してから続行」の分類（正本 grep で裏付け済み）:
  - 正本どおり・モックが古い: 一括印刷/一括破棄/一括登録の文言 6 行、04 cards_per_sheet（N-35・J9）、08 既定値として保存→「上書き保存」「別名で保存」（M20 :135）
  - 差異なし: 08「追加」は検索欄入力後に出る（モック初期は検索欄 "20261114"）、06 個別破棄は確認なし（M6 :70・N-09 :282 は一括のみ件数つき確認）
  - 前提データで未到達・TC で担保: 06 バッジ 2 行（N-14・N-18・N-72）
  - /im へ差し戻す: 03 印刷待ち一括のページ内確認 UI 3 行（M27/M28 :159,166 件数つき確認＋承認絵 manifest #15・16、03_held_bulk/inject.js:32-36。実装はネイティブ confirm）
  - 差し戻さない: 06「画像を選んで取り込む」（M3 :60 の「取り込みのみ」で置換済み）
  - J26 へ: 01「対象: 未取り込みの画像 n 件」・06「最終取り込み」「未取り込み n 件」（承認絵 #5・6・29・30 にあり、M 表・TC・7aacd05 のアプリに無い）
- spec の SKIP: e2e/tests/#1_main.pw.spec.ts の行頭 "// SKIP: " は 90 行 = B6・E16・N46（生成不可 68）＋P3・T4・X15（exclude 22）。test( は 87。前回メモ「未テスト 78」と 10 差（原因未確認）
- 再生成対象（advisor）: N-05・E-38（取り込みのみボタンが契約に無いで SKIP）＋確認方式不明で SKIP した 8 件（N-12 N-13 N-62 N-85 N-87 N-88 B-05 B-15）
- 別経路の既存テスト分類（scratchpad 0ec27344…/run1/classification.tsv）: S219/R183/P45/B36/未確定1=484。B1 は修正前の報告。新規論点 B2（10件: 11_8 N33・N36・N39・B09・B10・N72／11_6 B20／11_3 N02／cli_pipeline test_ingest_end_to_end・test_ingest_duplicate_and_lock。jobs/<job_id>/sheets/*.pdf が0件、報告者は pipeline.py:240 が jobs/_pdf/sheets/ に書くと指摘・確度中・未検証）
- fake lp（.vf/fakebin_main/lp）は引数を lp.log に追記して exit 0 するだけ

## 4. 未確定・仮説
### ユーザーへの確認事項
- 問い（J24・M28 印刷待ち）: 印刷待ちが0件のとき、一括操作のバー（全選択・一括印刷・一括破棄）を出しますか
  - 背景: tc-judge（セッション6）が B-14 を「弱い」と判定。正本 :225 の0件列にバーの記述が無く、文言だけでは改修前と見分けられない
  - 選択肢: A 0件ではバーを出さない（B-14 は Red を求めないデグレ確認 TC と明記）／B バーを出し一括印刷・一括破棄を disabled（B-14 に「disabled のまま」を足して Red にできる）
  - AI 推奨: A（承認済み mock 03 に0件の絵が無く、空の一覧に操作バーを出す利点が小さい）
  - 未回答の間の扱い: implementer は A を仮置き済み。/vf は止めない
  - 状態: 質問済み（セッション6）・未回答（セッション8 冒頭で全文再掲済み）
- 問い（J25・M15/M5/M24 既存テスト）: 改修で落ちる既存テスト 484 件を誰が直しますか
  - 背景: 正本 X-10 は 11_2・11_3・acceptance_extra・test_cli_pipeline・test_api の書き換えを「開発側作業」とするが、handoff 6節は tests/acceptance・test_spec_11_2〜11_8c を保護（変えるのは /st）。作った本人がテストを直すと検証の独立性が崩れる。分類結果は前 handoff 3節（B21 は修正済み）
  - 選択肢: A 保護対象（acceptance 2本・11_2〜11_8c）は /st（spec-tc 新規起動・正本と API の外形だけ渡す）、保護対象外の test_cli_pipeline・test_api だけ implementer（削除 TC は一覧報告）／B X-10 どおり列挙5ファイルは implementer、残り（11_4〜11_8c・acceptance.py）は /st／C 全件 /st
  - AI 推奨: A
  - 未回答の間の扱い: /vf は進める。/st（既存テスト）は回答待ち
  - 状態: 質問済み（セッション7）・未回答（セッション8 冒頭で全文再掲済み）
- 問い（J26・M3/M2 取り込み表示）: 承認済みモックにだけ写っている「対象: 未取り込みの画像 n 件」（取込&作成ダイアログ）と「最終取り込み <日時>」「未取り込み n 件」（取り込みタブ）を実装しますか
  - 背景: recon の DOM 契約突合で欠落（contract_diff_run1/run2）。manifest #5・6・29・30 の絵にはあるが、正本の M 表・TC にも改修前アプリ（7aacd05 web/index.html・app.js で grep 0件）にも無く、新しい集計機能になる。advisor は「黙って落とすのも黙って足すのも範囲逸脱」と判定
  - 選択肢: A 絵で承認済みなので実装する（/im、TC は /st で追加）／B モックの飾りとして正本に「表示しない」と追記（/st）
  - AI 推奨: A（advisor 推奨。絵で承認済み）
  - 未回答の間の扱い: Green は進める。この3項目は Green の判定対象外と報告に明記
  - 状態: 未質問（必要なら 03 ページ内確認とネイティブ confirm の方式統一も1行添える）
### 仮説・未確認
- 08_pdf_create_拡大_sp.png が幅 1629px（他 sp は 1170px）→ sp で拡大オーバーレイ時に横はみ出しの疑い。突合で確認
- SKIP 78 と 68 の 10 差の原因
- B2（PDF の出力先）が実装バグか：/vf Green 後、J25 と合わせて判定
- test-data 未確定2件・helper 追加で約15件生成可能・前 handoff 4節の残り（旧 11.8/11.8c DOM TC 判定記録なし・E-12 cards_per_sheet NULL・10スロットプレビュー API・fontTools 段階③）は前 handoff のとおり未着手
- E-26 の TC 強化（/st、spec-tc 新規）未着手

## 5. 却下した案と理由
前の handoff（1_card-master_print-edit_2.md・1_card-master_print-edit.md・main_print-edit_28.md）5節の行は全件有効。
| 案 | 却下理由 |
|---|---|
| REGEN=true で spec を全件再生成 | pw-loop の expect revert が新本文に基準 expect を差し込み混成ブロックになる（advisor・pw-loop.sh:99-106） |
| recon を省略して pw-triage に任せる | vf-recon.md:58,104 で省略不可・78件の生成不可を解く材料が recon にしかない |
| 「pw-gen は SKIP 分だけ」を本 spec で行う | pw-gen は SKIP 行を変えない（agents/pw-gen.md:16,23）→ 試行 spec（PW_SPEC_OUT='#1_main.skip.pw.spec.ts' PW_VF_DIR=.vf/skip）で行う |
| DOM 契約差分だけで 3-3 を通す | 絵との pc/sp 突合が無く sp 未確認は「判定不可」（vf-recon.md:72） |
| 06「画像を選んで取り込む」を /im へ差し戻す | 正本 M3 が「取り込みのみ」ボタンに置き換えた |
| :482「DOM の正本は inject.js」を機能追加の根拠にする | 形（ロケータ）の正本で、範囲は M 表が決める（advisor） |

## 6. 触ってはいけないもの
- 前 handoff 6節は全件有効（実機印刷・~/PrintEdit 書込禁止・tests/acceptance 等の期待値・main.md と #1_main.md 凍結・基準役プロンプトに実装 file:line を書かない・メインは fail_rows/error-context を読まず spec を直接 Edit しない・qkit 本体編集禁止・push なし・`cd … &&` 禁止・rm -rf 禁止・共有ファイル（playwright.config.ts・wt.ts・auth.setup.ts・package.json・test-accounts.local・bt_config.md）変更禁止・.vf/red の expect 固定版を変えない・.vf/seed/main.sh を改名しない・wt 撤去はユーザー許可・tests/ 配下）
- 8781（/mk 土台）を止めない

## 7. 次の一手
3-3 の続き: manifest（ai_docs/documents/main/mock/manifest.md）の after 全 42 行 × .vf/recon/*.png を pc/sp で突き合わせる表を照合役（新規起動・コンテキストを渡さず、パスだけ）に作らせる → gate_state の分類表を更新 → /im へ差し戻し（03 ページ内確認＋視覚差異を「箇所/期待/実際」TSV）・J26 をユーザーへ → /im 後に変わった画面だけ recon 撮り直し → recon サーバー 8791〜8794 停止 → 試行 spec で SKIP 10件 → Step 3.5 → pw-all.sh --resume 4 --until 4 → pw-all.sh（bg）→ pw-triage → pw-loop --final。
全体: /vf Green → J25 回答後の /st（既存テスト・E-26）→ pytest 全件 → /sr → main へ取り込み（git 管理外の .vf/e2e/ai_docs の戻し一覧）・次の /go（③テキスト系＋R10-5 濃さ）・周4 の仕様・README 化・11.9 `/st`・実機確認 X-01〜04・/ar Step 0 未消化 67 行（当初の指示 ai_docs/handoff/main_print-edit_3.md:2節）
