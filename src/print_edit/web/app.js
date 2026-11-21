const $ = (s) => document.querySelector(s);
const api = async (path, opt) => {
  const r = await fetch(path, opt);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status, body });
  return body;
};
const send = (method, path, body) =>
  api(path, body === undefined ? { method } : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const post = (p, body) => send("POST", p, body);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    k.startsWith("on") ? (e[k] = v) : e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) e.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return e;
};
const tag = (s) => el("span", { class: `tag ${s}` }, s);
const fileUrl = (p) => "/files/" + p;
const sheetImg = (id) => el("a", { href: `/api/sheets/${id}/image.png`, target: "_blank" },
  el("img", { src: `/api/sheets/${id}/image.png`, style: "max-width:320px;border:1px solid #ccc" }), el("br"), "クリックで原寸表示");
// サーバーの 422（配列）・409 などの detail を 1 本の文字列にする
const errText = (e) => {
  const d = e.body?.detail;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc ?? []).join(".")}${x.loc?.length ? ": " : ""}${x.msg}`).join(" / ");
  return d ?? e.message;
};
const dateOf = (c) => (c.job_created_at ?? "").slice(0, 10);
const cardLabel = (c) => `#${c.id} ${c.name || "（名前なし）"}`;
const summaryText = (r) => (r.failed === 0 ? `成功 ${r.success}件` : `成功 ${r.success}件 / 失敗 ${r.failed}件`);
const STATUS_LABEL = { sent: "送信済み", error: "エラー", held: "印刷待ち", created: "作成済み", discarded: "破棄済み", sending: "送信中" };

// ---- タブ ----
const views = { ingest: renderIngest, master: renderMaster, pdf: renderPdf, history: renderHistory, held: renderHeld, presets: renderPresets, settings: renderSettings };
const secId = (k) => (k === "master" ? "master-view" : k);
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
function show(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  for (const k of Object.keys(views)) $("#" + secId(k)).hidden = k !== name;
  views[name]().catch((e) => ($("#" + secId(name)).textContent = "読み込み失敗: " + e.message));
}
const current = () => document.querySelector("#tabs .active").dataset.tab;

// ---- 取込&作成ダイアログ ----
$("#ingest-btn").addEventListener("click", async () => {
  if ($("#ingest-dialog")) return;
  let presets, cfg;
  try { [presets, cfg] = await Promise.all([api("/api/presets"), api("/api/config")]); }
  catch (e) { alert("取込&作成失敗: " + errText(e)); return; }
  const sel = el("select", {}, presets.map((p) => el("option", { value: p.id }, p.name)));
  const last = presets.find((p) => p.id === cfg.last_preset_id) ?? presets.find((p) => p.builtin) ?? presets[0];
  sel.value = last.id;
  const close = () => ov.remove();
  const run = el("button", { type: "button", style: "font-weight:bold" }, "実行");
  run.onclick = async () => {
    run.disabled = true;
    let r;
    try { r = await post("/api/ingest/create", { preset_id: Number(sel.value) }); }
    catch (e) {
      close();
      if (e.status === 409) alert("別の取り込みが実行中です。終わってから押してください");
      else alert("取込&作成失敗: " + errText(e));
      return;
    }
    close();
    alert(r.results.length === 0 ? "取り込む対象がありませんでした" : `取り込み ${r.cards}件・PDF ${r.pdfs}件を作成しました`);
    show(current());
  };
  const ov = el("div", { id: "ingest-dialog", role: "dialog", "aria-modal": "true", class: "overlay" },
    el("div", { class: "dlg" },
      el("h3", {}, "取込&作成"),
      el("p", {}, "監視フォルダの新しい画像を取り込み、選んだ既定値で PDF を作成します。取り込んだ名刺は登録待ちに入ります（マスタには自動で登録しません）。"),
      el("label", {}, "使う既定値 ", sel),
      el("div", { class: "dlg-btns" }, el("button", { type: "button", onclick: close }, "キャンセル"), " ", run)));
  document.body.append(ov);
});

// ---- 取り込み（登録待ち）----
let queueSel = new Set();
function resultBox(title, r, rows) {
  return el("div", { class: "resbox", id: "bulk-result" }, el("b", {}, title), el("div", {}, summaryText(r)),
    rows.length ? el("ul", {}, rows.map(([ok, text]) => el("li", { class: ok ? "res-ok" : "res-ng" }, text))) : "");
}
async function renderIngest(result = null) {
  const root = $("#ingest");
  const [cards, info] = await Promise.all([api("/api/cards?reg=pending"), api("/api/info")]);
  queueSel = new Set([...queueSel].filter((id) => cards.some((c) => c.id === id)));
  const act = (what, fn) => async () => {
    try { await fn(); } catch (e) { alert(`${what}失敗: ${errText(e)}`); }
    await renderIngest();
  };
  const only = el("button", { type: "button", id: "ingest-only" }, "取り込みのみ");
  only.onclick = async () => {
    let r;
    try { r = await post("/api/ingest"); }
    catch (e) {
      if (e.status === 409) { alert("別の取り込みが実行中です。終わってから押してください"); return; }
      alert("取り込み失敗: " + errText(e)); return;
    }
    alert(r.length === 0 ? "取り込む対象がありませんでした" : `${r.length} 件処理しました`);
    await renderIngest();
  };
  const all = el("input", { type: "checkbox", id: "queue-all" });
  const bulkOk = el("button", { type: "button", id: "bulk-register" });
  const bulkNg = el("button", { type: "button", id: "bulk-discard-cards" });
  const bulk = (path, label, title) => async () => {
    const ids = [...queueSel];
    if (!confirm(`${ids.length}件を${label}します。よろしいですか`)) return;
    let r;
    try { r = await post(path, { ids }); } catch (e) { alert(`${label}失敗: ${errText(e)}`); return; }
    queueSel.clear();
    await renderIngest(resultBox(title, r, r.results.filter((x) => !x.ok).map((x) => [false, `失敗 #${x.id} ${x.source_name ?? ""}: ${x.detail}`])));
  };
  bulkOk.onclick = bulk("/api/bulk/cards/register", "登録", "一括登録の結果");
  bulkNg.onclick = bulk("/api/bulk/cards/discard", "破棄", "一括破棄の結果");
  const boxes = new Map();
  const sync = () => {
    const n = queueSel.size;
    bulkOk.textContent = `一括登録（${n}件）`;
    bulkNg.textContent = `一括破棄（${n}件）`;
    bulkOk.disabled = bulkNg.disabled = n === 0;
    all.checked = cards.length > 0 && n === cards.length;
    all.indeterminate = n > 0 && n < cards.length;
    boxes.forEach(([cb, card], id) => card.classList.toggle("on", queueSel.has(id)));
  };
  all.onchange = () => { queueSel = new Set(all.checked ? cards.map((c) => c.id) : []); boxes.forEach(([cb], id) => (cb.checked = queueSel.has(id))); sync(); };
  const grid = el("div", { class: "cgrid", id: "queue" });
  for (const c of cards) {
    const cb = el("input", { type: "checkbox" });
    cb.checked = queueSel.has(c.id);
    cb.onchange = () => { cb.checked ? queueSel.add(c.id) : queueSel.delete(c.id); sync(); };
    const badges = [c.used ? "取込&作成で使用済み" : null, c.migrated ? "移行分" : null].filter(Boolean);
    const card = el("div", { class: "ccard" }, cb, el("img", { src: fileUrl(c.image_path), loading: "lazy", alt: c.source_name ?? "" }),
      el("div", { class: "info" },
        el("div", {}, c.source_name ?? "-"), el("div", {}, `取込日 ${dateOf(c)}`),
        badges.length ? el("div", {}, badges.map((b) => [el("span", { class: "badge" }, b), " "])) : "",
        el("div", {},
          el("button", { type: "button", onclick: act("登録", () => post(`/api/cards/${c.id}/register`)) }, "マスタに登録"), " ",
          el("button", { type: "button", onclick: act("回転", () => post(`/api/cards/${c.id}/rotate`)) }, "180度回転"), " ",
          el("button", { type: "button", onclick: act("破棄", () => post(`/api/cards/${c.id}/discard`)) }, "破棄"))));
    boxes.set(c.id, [cb, card]);
    grid.append(card);
  }
  root.replaceChildren(el("h2", {}, "取り込み"),
    el("fieldset", {}, el("legend", {}, "スキャン画像"), el("div", { class: "bar" }, only, el("span", {}, "フォルダ監視"), el("code", {}, info.inbox_dir))),
    el("h3", {}, `登録待ち（${cards.length}件）`),
    result ?? "",
    el("div", { class: "bar" }, el("label", {}, all, "すべて選択"), bulkOk, bulkNg),
    el("div", { class: "hint" }, "取込&作成で PDF に使った名刺も、登録または破棄するまでここに残ります。"),
    cards.length ? grid : el("div", {}, "登録待ちの名刺はありません"));
  sync();
}

// ---- 名刺マスタ ----
let masterSel = new Set(), masterQ = "", masterSeq = 0;
async function renderMaster() {
  const root = $("#master-view");
  const search = el("input", { type: "text", placeholder: "名前・元ファイル名・取込日（部分一致）", style: "width:22em;max-width:70vw" });
  search.value = masterQ;
  const count = el("span", { class: "hint" });
  const pdfBtn = el("button", { type: "button", style: "font-weight:bold" });
  const clear = el("button", { type: "button" }, "選択を解除");
  const grid = el("div", { class: "cgrid", id: "master" });
  const empty = el("div", {}, "該当する名刺はありません");
  root.replaceChildren(el("h2", {}, "名刺マスタ"),
    el("div", { class: "bar" }, el("label", {}, "検索", " ", search), count),
    el("div", { class: "bar" }, pdfBtn, clear), grid, empty);
  const syncBar = () => {
    pdfBtn.textContent = `PDF 作成（${masterSel.size}件）`;
    pdfBtn.disabled = masterSel.size === 0;
  };
  pdfBtn.onclick = async () => {
    try { PDF = await pdfFromCards([...masterSel]); } catch (e) { alert("PDF 作成画面を開けませんでした: " + errText(e)); return; }
    show("pdf");
  };
  clear.onclick = () => { masterSel.clear(); grid.querySelectorAll(".ccard").forEach((c) => { c.classList.remove("on"); c.querySelector("input[type=checkbox]").checked = false; }); syncBar(); };
  const load = async () => {
    const my = ++masterSeq;
    const [list, all] = await Promise.all([api("/api/cards?reg=master&q=" + encodeURIComponent(masterQ)), masterQ ? api("/api/cards?reg=master") : null]);
    if (my !== masterSeq) return;
    count.textContent = `${(all ?? list).length}件中 ${list.length}件を表示`;
    grid.replaceChildren(...list.map((c) => masterCard(c, syncBar, load)));
    empty.hidden = list.length > 0;
    syncBar();
  };
  let timer = null;
  search.addEventListener("input", () => { masterQ = search.value.trim(); clearTimeout(timer); timer = setTimeout(load, 200); });
  await load();
}
function masterCard(c, syncBar, reload) {
  const cb = el("input", { type: "checkbox" });
  cb.checked = masterSel.has(c.id);
  const card = el("div", { class: "ccard" + (cb.checked ? " on" : "") }, cb);
  cb.onchange = () => { cb.checked ? masterSel.add(c.id) : masterSel.delete(c.id); card.classList.toggle("on", cb.checked); syncBar(); };
  const nameIn = el("input", { type: "text", placeholder: "名前を入力" });
  nameIn.value = c.name ?? "";
  const nameView = el("div", { class: "name-view" }, c.name || "（名前なし）");
  const saveName = async () => {
    try {
      const r = await send("PUT", `/api/cards/${c.id}/name`, { name: nameIn.value });
      nameIn.value = r.name ?? "";
      nameView.textContent = r.name || "（名前なし）";
    } catch (e) { alert("名前の保存失敗: " + errText(e)); }
  };
  const del = async () => {
    if (!confirm("この名刺をマスタから削除しますか？（画像と、履歴の調整・再印刷には影響しません）")) return;
    try { await send("DELETE", `/api/cards/${c.id}`); masterSel.delete(c.id); } catch (e) { alert("削除失敗: " + errText(e)); }
    await reload();
  };
  card.append(el("img", { src: fileUrl(c.image_path), loading: "lazy", alt: "" }),
    el("div", { class: "info" }, el("div", {}, `#${c.id}`), nameView,
      el("div", {}, nameIn, el("button", { type: "button", onclick: saveName }, "名前を保存")),
      el("div", {}, c.source_name ?? "-"), el("div", {}, `取込日 ${dateOf(c)}`),
      el("div", {}, el("button", { type: "button", onclick: del }, "マスタから削除"))));
  return card;
}

// ---- 履歴 ----
async function renderHistory() {
  const root = $("#history");
  const rows = await api("/api/history");
  root.replaceChildren(el("h2", {}, "履歴"));
  if (!rows.length) root.append("ジョブはありません");
  const sheetLine = (s) => {
    const btns = el("span", {});
    if (s.status === "sent" || s.status === "error") {
      btns.append(el("button", { type: "button", onclick: async () => {
        try {
          const r = await post(`/api/sheets/${s.id}/reprint`);
          alert(r.output === "pdf" ? "出力先が pdf のため印刷していません（PDF は保存済み）" : "再送しました");
        } catch (e) { alert("再印刷失敗: " + errText(e)); }
        await renderHistory();
      } }, "再印刷"));
    }
    btns.append(el("button", { type: "button", onclick: async () => {
      try { PDF = await pdfFromAdjust(await api(`/api/sheets/${s.id}/adjust`)); } catch (e) { alert("調整する失敗: " + errText(e)); return; }
      show("pdf");
    } }, "調整する"));
    return el("div", { class: "sheet-line", "data-sheet": s.id }, el("a", { href: fileUrl(s.pdf_path), target: "_blank" }, s.pdf_path), " ", tag(s.status), s.error ?? "", btns, el("br"), sheetImg(s.id));
  };
  for (const j of rows) {
    const box = el("div", { class: "job" });
    const detail = el("div");
    if (j.kind === "pdf") {
      box.append(el("div", {}, "PDF 作成 ", `#${j.id} `, tag(j.status), ` ${j.created_at} カード${new Set(j.cards.map((c) => c.card_id)).size}種 `));
      box.append(el("button", { type: "button", onclick: () => detail.replaceChildren(sheetLine(j)) }, "詳細"), detail);
    } else {
      box.append(el("div", {}, `${j.id} `, tag(j.status), ` ${j.source_name} / ${j.dpi ?? "-"}dpi / カード${j.card_count} シート${j.sheet_count} `, j.warnings.join(",")));
      box.append(el("button", { type: "button", onclick: async () => {
        const d = await api("/api/jobs/" + j.id);
        detail.replaceChildren(
          el("div", { class: "row" },
            el("div", {}, "原画像", el("br"), el("img", { src: fileUrl(`jobs/${j.id}/source.png`) })),
            d.cards.map((c) => el("div", { class: "card" }, el("img", { src: fileUrl(c.image_path) }), el("br"), `#${c.idx} `, tag(c.status)))),
          ...(d.sheets.length ? d.sheets.map(sheetLine) : [el("div", {}, "PDF はありません")]));
      } }, "詳細"), detail);
    }
    root.append(box);
  }
}

// ---- 印刷待ち ----
let heldSel = new Set();
// 一括印刷・一括破棄の件数つき確認（ページ内）。実行で true、キャンセルで false
function confirmDlg(text, okLabel) {
  return new Promise((resolve) => {
    const done = (v) => () => { ov.remove(); resolve(v); };
    const ov = el("div", { id: "confirm-dialog", role: "dialog", "aria-modal": "true", class: "overlay" },
      el("div", { class: "dlg" },
        el("p", { style: "margin:0" }, text),
        el("div", { class: "dlg-btns" }, el("button", { type: "button", onclick: done(false) }, "キャンセル"), " ", el("button", { type: "button", style: "font-weight:bold", onclick: done(true) }, okLabel))));
    document.body.append(ov);
  });
}
async function renderHeld(opts = {}) {
  const root = $("#held");
  const sheets = await api("/api/sheets?status=held");
  heldSel = new Set([...heldSel].filter((id) => sheets.some((s) => s.id === id)));
  root.replaceChildren(el("h2", {}, "印刷待ち"));
  if (opts.notice) root.append(el("div", { class: "error", id: "held-notice" }, opts.notice));
  if (opts.result) root.append(opts.result);
  if (!sheets.length) root.append("印刷待ちのシートはありません");
  const act = (s, op) => async () => {
    if (op === "discard" && !confirm("このシートを破棄しますか？")) return;
    let msg;
    try {
      const r = await post(`/api/sheets/${s.id}/${op}`);
      if (op === "discard") msg = "破棄しました";
      else msg = r.output === "pdf" ? "出力先が pdf のため印刷していません（PDF は保存済み）" : "印刷しました";
    } catch (e) {
      if (e.status === 404) msg = "シートが見つかりません";
      else if (e.status === 409) msg = "このシートは既に処理されています";
      else if (op === "print" && e.status === 400) msg = "印刷に失敗しました: " + (e.body?.detail ?? e.message);
      else msg = "失敗: " + errText(e);
    }
    await renderHeld({ notice: msg });
  };
  const all = el("input", { type: "checkbox", id: "held-all" });
  const bulkPrint = el("button", { type: "button", id: "bulk-print" });
  const bulkDiscard = el("button", { type: "button", id: "bulk-discard" });
  const rowsEl = new Map();
  const sync = () => {
    const n = heldSel.size;
    bulkPrint.textContent = `一括印刷（${n}件）`;
    bulkDiscard.textContent = `一括破棄（${n}件）`;
    bulkPrint.disabled = bulkDiscard.disabled = n === 0;
    all.checked = sheets.length > 0 && n === sheets.length;
    all.indeterminate = n > 0 && n < sheets.length;
    rowsEl.forEach(([cb, card], id) => card.classList.toggle("sel", heldSel.has(id)));
  };
  all.onchange = () => { heldSel = new Set(all.checked ? sheets.map((s) => s.id) : []); rowsEl.forEach(([cb], id) => (cb.checked = heldSel.has(id))); sync(); };
  const bulk = (op, label) => async () => {
    const ids = [...heldSel];
    if (!(await confirmDlg(`${ids.length}件を${label}します。よろしいですか`, `${label}する`))) return;
    let r;
    try { r = await post(`/api/bulk/sheets/${op}`, { ids }); } catch (e) { alert(`${label}失敗: ${errText(e)}`); return; }
    heldSel.clear();
    const lines = r.results.map((x) => [x.ok, `${x.ok ? "成功" : "失敗"} #${x.sheet_id} ${x.detail}`]);
    await renderHeld({ result: resultBox(`一括${label}の結果`, r, lines) });
  };
  bulkPrint.onclick = bulk("print", "印刷");
  bulkDiscard.onclick = bulk("discard", "破棄");
  if (sheets.length) root.append(el("div", { class: "bulkbar" }, el("label", { style: "display:inline-flex;align-items:center;gap:6px;margin:0" }, all, "全選択"), bulkPrint, bulkDiscard));
  for (const s of sheets) {
    const cb = el("input", { type: "checkbox", class: "pick-cb" });
    cb.checked = heldSel.has(s.id);
    cb.onchange = () => { cb.checked ? heldSel.add(s.id) : heldSel.delete(s.id); sync(); };
    const card = el("div", { class: "card", "data-sheet": s.id },
      el("label", { class: "pick" }, cb, `選択 #${s.id}`),
      sheetImg(s.id), el("br"),
      `#${s.id} ${s.job_id ?? "(PDF 作成)"} ${s.created_at} カード${s.card_count}枚 `, el("a", { href: fileUrl(s.pdf_path), target: "_blank" }, "PDF"), el("br"),
      el("button", { type: "button", onclick: act(s, "print") }, "印刷する"), " ",
      el("button", { type: "button", onclick: act(s, "discard") }, "破棄"));
    rowsEl.set(s.id, [cb, card]);
    root.append(card);
  }
  sync();
}

// ---- 設定（JSON Schema から生成） ----
const resolve = (schema, ref) => schema.$defs[ref.split("/").pop()];
const sectionDef = (schema, sp) => resolve(schema, sp.$ref ?? sp.allOf[0].$ref);
const unwrap = (p) => {
  if (p.anyOf) { const non = p.anyOf.filter((x) => x.type !== "null"); return { ...p, ...non[0], nullable: non.length < p.anyOf.length }; }
  return p;
};
function field(section, key, prop, value) {
  const p = unwrap(prop);
  const label = el("label", {}, p.title ?? key, p.description ? el("span", { class: "desc" }, p.description) : "");
  let input;
  if (p.enum) {
    input = el("select", {}, p.enum.map((v) => el("option", { value: v }, v)));
    input.value = value;
  } else if (p.type === "boolean") {
    input = el("input", { type: "checkbox" }); input.checked = !!value;
  } else if (p.type === "integer" || p.type === "number") {
    input = el("input", { type: "number", step: p.type === "integer" ? "1" : "any" });
    input.value = value ?? "";
  } else if (p.type === "array") {
    input = el("input", { type: "text", style: "width:24em" }); input.value = (value ?? []).join(",");
  } else {
    input = el("input", { type: "text", style: "width:24em" }); input.value = value ?? "";
  }
  input.dataset.section = section; input.dataset.key = key; input.dataset.kind = p.type ?? "enum"; input.dataset.nullable = p.nullable ? "1" : "";
  label.prepend(input, " ");
  return label;
}
function readForm(root) {
  const out = {};
  root.querySelectorAll("[data-key]").forEach((i) => {
    const { section, key, kind, nullable } = i.dataset;
    let v;
    if (kind === "boolean") v = i.checked;
    else if (kind === "integer") v = i.value === "" ? (nullable ? null : 0) : parseInt(i.value, 10);
    else if (kind === "number") v = i.value === "" ? (nullable ? null : 0) : parseFloat(i.value);
    else if (kind === "array") v = i.value.split(",").map((x) => x.trim()).filter(Boolean);
    else v = i.value;
    (out[section] ??= {})[key] = v;
  });
  return out;
}
// プリンタが持つ印刷オプション（lpoptions）を選択肢で出し、選ぶと「lp オプション」欄に 名前=値 を書く（欄は残す）
function lpPicker(root) {
  const listIn = root.querySelector('[data-key="lp_options"]');
  const nameIn = root.querySelector('[data-key="printer_name"]');
  const box = el("div", { class: "lp-picker" });
  let opts = [];
  const keyOf = (s) => s.split("=")[0].trim().toLowerCase();
  const items = () => listIn.value.split(",").map((x) => x.trim()).filter(Boolean);
  const current = (key) => { const s = items().find((x) => keyOf(x) === key.toLowerCase()); return s === undefined ? "" : s.slice(s.indexOf("=") + 1); };
  const write = (key, val) => {
    const cur = items(), i = cur.findIndex((x) => keyOf(x) === key.toLowerCase());
    if (!val) { if (i >= 0) cur.splice(i, 1); } else if (i >= 0) cur[i] = `${key}=${val}`; else cur.push(`${key}=${val}`);
    listIn.value = cur.join(",");
    listIn.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const selects = [];
  const row = (o) => {
    const sel = el("select", {});
    // プリンタの既定値は書かない（空 = 既定のまま）。一覧に無い現在値は消さずに選択肢へ足す
    const lab = (v) => (o.choice_labels && o.choice_labels[v]) || v;
    sel.append(el("option", { value: "" }, `（既定${o.default ? `: ${lab(o.default)}` : ""}）`));
    for (const v of o.choices) if (v !== o.default) sel.append(el("option", { value: v }, lab(v)));
    const cur = current(o.key);
    if (cur && !o.choices.includes(cur)) sel.append(el("option", { value: cur }, `${cur}（現在値）`));
    sel.addEventListener("change", () => write(o.key, sel.value));
    selects.push([o, sel]);
    return el("label", {}, `${o.label}（${o.key}） `, sel);
  };
  const sync = () => selects.forEach(([o, sel]) => {
    const cur = current(o.key);
    sel.value = cur && cur !== o.default && [...sel.options].some((x) => x.value === cur) ? cur : "";
  });
  const load = async () => {
    selects.length = 0;
    box.replaceChildren(el("div", { class: "hint" }, "プリンタの印刷オプションを読み込み中…"));
    let r;
    try { r = await api("/api/printer/options?name=" + encodeURIComponent(nameIn.value.trim())); }
    catch (e) { r = { options: [], error: "取得に失敗しました: " + e.message }; }
    opts = r.options;
    if (r.error) { box.replaceChildren(el("div", { class: "err" }, `${r.error}（下の「lp オプション」欄に直接入力できます）`)); return; }
    // AirPrint の print-quality があれば画質はそれ（cupsPrintQuality は PPD 用で AirPrint には届かない）。無ければ従来どおり
    const hasIpp = opts.some((o) => o.key === "print-quality");
    const isQuality = (o) => (hasIpp ? o.key === "print-quality" : /^(cupsPrintQuality|Resolution)$/i.test(o.key));
    const head = el("div", {}, el("b", {}, `プリンタ ${r.printer} の画質`), el("br"), ...opts.filter(isQuality).map(row));
    const more = el("details", {}, el("summary", {}, "そのほかの印刷オプション"), ...opts.filter((o) => !isQuality(o)).map((o) => el("div", {}, row(o))));
    box.replaceChildren(head, more);
    sync();
  };
  listIn.addEventListener("input", sync);
  nameIn.addEventListener("change", load);
  load();
  return box;
}

// ---- 全体設定 ----
async function renderSettings() {
  const root = $("#settings");
  const [schema, cfg, info, presets] = await Promise.all([api("/api/config/schema"), api("/api/config"), api("/api/info"), api("/api/presets")]);
  root.replaceChildren(el("h2", {}, "全体設定"));
  root.append(el("div", { class: "hint", style: "overflow-wrap:anywhere" }, el("b", {}, "iPrint&Scan 側で合わせる値"), el("br"),
    `保存先: ${info.inbox_dir}`, el("br"), "形式: PNG", el("br"), `解像度: ${info.expected_dpi} dpi`));
  const form = el("form");
  const ai = cfg.auto_ingest;
  const ra = el("input", { type: "radio", name: "auto" }), rb = el("input", { type: "radio", name: "auto" });
  (ai.mode === "ingest_only" ? ra : rb).checked = true;
  const ps = el("select", {}, presets.map((p) => el("option", { value: p.id }, p.name)));
  ps.value = (presets.find((p) => p.id === ai.preset_id) ?? presets.find((p) => p.builtin) ?? presets[0]).id;
  form.append(el("fieldset", {}, el("legend", {}, "フォルダ監視の自動取り込み"),
    el("div", { class: "radio-row" }, el("label", {}, ra, "取り込みのみ"), el("span", { class: "auto-create" }, el("label", {}, rb, "取込&作成"), " （", el("label", {}, "使う既定値 ", ps), "）")),
    el("div", { class: "desc", style: "color:#777;font-size:12px" }, "監視フォルダに画像が届いたときの動作。取込&作成は選んだ既定値で PDF も作る（取り込んだ名刺は登録待ちに入り、マスタには自動で登録しない）")));
  for (const section of ["intake", "detect", "print", "device"]) {
    const sp = schema.properties[section];
    const fs = el("fieldset", {}, el("legend", {}, sp.title ?? section));
    for (const [key, prop] of Object.entries(sectionDef(schema, sp).properties)) fs.append(field(section, key, prop, cfg[section][key]));
    if (section === "print") fs.append(lpPicker(fs));
    form.append(fs);
  }
  const msg = el("div", { class: "err" });
  form.append(el("button", { type: "submit" }, "保存"), msg);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const body = { ...readForm(form), auto_ingest: { mode: ra.checked ? "ingest_only" : "ingest_create", preset_id: Number(ps.value) } };
    try { await send("PUT", "/api/config", body); msg.textContent = "保存しました"; msg.className = ""; }
    catch (e) { msg.className = "err"; msg.textContent = errText(e); }
  });
  root.append(form);
}

// ---- 面付け図（設定作成のスロット図・PDF 作成のプレビュー）----
function previewNodes(lay, opts = {}) {
  const info = el("div", {}, `容量 ${lay.capacity} 枚（${lay.columns} 列 × ${lay.rows} 行、${lay.card_rotated ? "縦置き" : "横置き"}）`);
  const [pw, ph] = lay.paper_mm, [x, y, w, h] = lay.printable_mm;
  const ns = "http://www.w3.org/2000/svg";
  const n = (t, a) => { const e = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
  const svg = n("svg", { viewBox: `0 0 ${pw} ${ph}`, width: pw * 2.5 });
  svg.append(n("rect", { x: 0, y: 0, width: pw, height: ph, fill: "#fff" }));
  svg.append(n("rect", { x, y, width: w, height: h, fill: "none", stroke: "#c00", "stroke-dasharray": "2" }));
  for (const s of lay.slots) {
    const g = n("g", { "data-slot": s.index });
    const card = opts.assign?.[s.index];
    if (opts.assign) {
      if (card) {
        const [cx, cy] = [s.x + s.w / 2, s.y + s.h / 2];
        const img = lay.card_rotated
          ? n("image", { href: fileUrl(card.image_path), x: cx - s.h / 2, y: cy - s.w / 2, width: s.h, height: s.w, preserveAspectRatio: "xMidYMid slice", transform: `rotate(-90 ${cx} ${cy})` })
          : n("image", { href: fileUrl(card.image_path), x: s.x, y: s.y, width: s.w, height: s.h, preserveAspectRatio: "xMidYMid slice" });
        g.append(img);
        g.append(n("rect", { x: s.x + s.w - 16, y: s.y + s.h - 7, width: 14, height: 5.5, fill: "rgba(0,0,0,.65)" }));
        const t = n("text", { x: s.x + s.w - 9, y: s.y + s.h - 3, "text-anchor": "middle", "font-size": 3.8, fill: "#fff" }); t.textContent = `#${card.id}`; g.append(t);
      } else {
        g.append(n("rect", { x: s.x, y: s.y, width: s.w, height: s.h, fill: "#f4f4f4", stroke: "#aaa", "stroke-dasharray": "2" }));
        const t = n("text", { x: s.x + s.w / 2, y: s.y + s.h / 2, "text-anchor": "middle", "font-size": 5, fill: "#888" }); t.textContent = "空き"; g.append(t);
      }
      g.append(n("circle", { cx: s.x + 4.5, cy: s.y + 4.5, r: 3.6, fill: "#333" }));
      const t = n("text", { x: s.x + 4.5, y: s.y + 6, "text-anchor": "middle", "font-size": 4.4, fill: "#fff" }); t.textContent = s.index; g.append(t);
      if (opts.sel === s.index) g.append(n("rect", { x: s.x, y: s.y, width: s.w, height: s.h, fill: "none", stroke: "#06c", "stroke-width": 1.4 }));
    } else {
      // 名刺間トンボと見分けるため枠線は引かず、市松の 2 色で隣の名刺を区別する
      const c = (s.index - 1) % lay.columns, r = Math.floor((s.index - 1) / lay.columns);
      g.append(n("rect", { x: s.x, y: s.y, width: s.w, height: s.h, fill: (c + r) % 2 ? "#cfdcf2" : "#e8eff9" }));
      const t = n("text", { x: s.x + s.w / 2, y: s.y + s.h / 2, "text-anchor": "middle", "font-size": 6 }); t.textContent = s.card; g.append(t);
    }
    svg.append(g);
  }
  const [cx, cy] = [x + w / 2, y + h / 2];
  const dashed = lay.mark_style === "dashed";
  for (const m of lay.marks) {
    let [x1, y1, x2, y2] = [m.x1, m.y1, m.x2, m.y2];
    if (dashed && (x1 - cx) ** 2 + (y1 - cy) ** 2 > (x2 - cx) ** 2 + (y2 - cy) ** 2) [x1, y1, x2, y2] = [x2, y2, x1, y1];
    const a = { x1, y1, x2, y2, stroke: "#000", "stroke-width": 0.2 };
    if (dashed) a["stroke-dasharray"] = `${lay.mark_dash_mm} ${lay.mark_gap_mm}`;
    svg.append(n("line", a));
  }
  for (const m of lay.inner_marks || []) {
    const a = { x1: m.x1, y1: m.y1, x2: m.x2, y2: m.y2, stroke: "#000", "stroke-width": 0.35 };
    if (dashed) a["stroke-dasharray"] = `${lay.mark_dash_mm} ${lay.mark_gap_mm}`;
    svg.append(n("line", a));
  }
  return [info, svg];
}
// クリックで拡大。ホイールで拡大縮小、＋－ボタン、クリックか Esc で閉じる
function zoomSvg(svg, caption) {
  if ($("#zoom")) return;
  const big = svg.cloneNode(true);
  const [, , vw, vh] = svg.getAttribute("viewBox").split(" ").map(Number);
  let width = Math.min(innerWidth - 24, (innerHeight * 0.86 * vw) / vh);
  const apply = () => { big.style.cssText = `width:${width}px;height:auto;max-width:none;max-height:none;background:#fff;cursor:zoom-out`; };
  const scale = (f) => { width = Math.min(Math.max(width * f, 120), 4000); apply(); };
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  apply();
  big.onclick = close;
  const ov = el("div", { id: "zoom", class: "overlay zoom" },
    el("div", { class: "zoom-bar" },
      el("button", { type: "button", onclick: () => scale(1.25) }, "＋"), el("button", { type: "button", onclick: () => scale(0.8) }, "－"), el("button", { type: "button", onclick: close }, "閉じる"),
      "ホイールで拡大縮小・クリックか Esc で閉じる", ` ${caption ?? ""}`),
    big);
  ov.addEventListener("wheel", (e) => { e.preventDefault(); scale(e.deltaY < 0 ? 1.1 : 1 / 1.1); }, { passive: false });
  document.addEventListener("keydown", onKey);
  document.body.append(ov);
}
// 250ms デバウンス＋AbortController＋seq 番号で、入力のたびの POST を抑え古い応答を捨てる
function livePreview(getBody, onLayout, onError) {
  let seq = 0, timer = null, ctrl = null;
  const refresh = async () => {
    const my = ++seq;
    ctrl?.abort(); ctrl = new AbortController();
    try {
      const lay = await post("/api/layout/preview", getBody(), undefined);
      if (my !== seq) return;
      onLayout(lay);
    } catch (e) {
      if (e.name === "AbortError" || my !== seq) return;
      onError(e);
    }
  };
  const run = async () => {
    const my = ++seq;
    ctrl?.abort(); ctrl = new AbortController();
    try {
      const lay = await api("/api/layout/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(getBody()), signal: ctrl.signal });
      if (my !== seq) return;
      onLayout(lay);
    } catch (e) {
      if (e.name === "AbortError" || my !== seq) return;
      onError(e);
    }
  };
  return { now: run, later: () => { clearTimeout(timer); timer = setTimeout(run, 250); }, refresh };
}

// ---- 並べ方（まとめ方・1名刺あたりの枚数・並べ順）。設定作成と PDF 作成で共通 ----
let radioUid = 0;
function arrangeFieldset(a, onChange, perCardDesc = "") {
  const grp = el("select", {}, el("option", { value: "single" }, "1名刺1PDF"), el("option", { value: "multi" }, "複数名刺1PDF"));
  const ord = el("select", {}, el("option", { value: "row" }, "行優先"), el("option", { value: "col" }, "列優先"));
  const name = `pc-${++radioUid}`;
  const num = el("input", { type: "number", min: "1", style: "width:5em" });
  const r1 = el("input", { type: "radio", name }), r2 = el("input", { type: "radio", name });
  grp.value = a.group; ord.value = a.order; num.value = a.per_card ?? 1;
  r1.checked = a.per_card !== null; r2.checked = a.per_card === null;
  const fire = () => {
    a.group = grp.value; a.order = ord.value;
    a.per_card = r2.checked ? null : Math.max(1, parseInt(num.value, 10) || 1);
    onChange();
  };
  [grp, ord, r1, r2].forEach((x) => x.addEventListener("change", fire));
  num.addEventListener("input", () => { r1.checked = true; fire(); });
  return el("fieldset", {}, el("legend", {}, "並べ方"),
    el("label", {}, "まとめ方 ", grp, el("span", { class: "desc" }, "複数名刺1PDF は別々の名刺を同じ PDF に並べる")),
    el("div", {}, "1名刺あたりの枚数", el("div", { class: "radio-row" }, el("label", {}, r1, "数値 ", num, " 枚"), el("label", {}, r2, "全部埋める")), perCardDesc ? el("span", { class: "desc" }, perCardDesc) : ""),
    el("label", {}, "並べ順 ", ord, el("span", { class: "desc" }, "行優先は左から右へ、列優先は上から下へ並べる")));
}
// 既定値の補正・面付けフォーム（cards_per_sheet を出すかは skip で決める）
function presetFields(schema, data, skip = []) {
  const out = [];
  for (const [section, label] of [["correct", "補正"], ["layout", "面付け"]]) {
    const def = sectionDef(schema, schema.properties[section]);
    const fs = el("fieldset", {}, el("legend", {}, label));
    for (const [key, prop] of Object.entries(def.properties)) { if (section === "layout" && skip.includes(key)) continue; fs.append(field(section, key, prop, data[section][key])); }
    out.push(fs);
  }
  return out;
}

// ---- 設定作成（既定値）----
let presetSel = null;
async function renderPresets() {
  const root = $("#presets");
  const [schema, presets] = await Promise.all([api("/api/presets/schema"), api("/api/presets")]);
  let cur = presets.find((p) => p.id === presetSel) ?? (presetSel === 0 ? null : presets[0]);
  presetSel = cur ? cur.id : 0;
  const isNew = cur === null;
  const data = structuredClone(cur ? cur.data : presets.find((p) => p.builtin).data);
  const reload = async () => renderPresets();
  const li = (p) => {
    const item = el("li", { class: p.id === presetSel ? "on" : "" }, p.name, p.builtin ? el("small", {}, "（自動作成）") : "");
    item.onclick = () => { presetSel = p.id; renderPresets(); };
    return item;
  };
  const bNew = el("button", { type: "button" }, "新規");
  const bRename = el("button", { type: "button", disabled: isNew }, "名前を変更");
  const bDel = el("button", { type: "button", disabled: isNew || cur.builtin }, "削除");
  bNew.onclick = () => { presetSel = 0; renderPresets(); };
  bRename.onclick = async () => {
    const name = prompt("新しい名前", cur.name);
    if (name === null) return;
    try { await send("PUT", `/api/presets/${cur.id}`, { name }); } catch (e) { alert("名前の変更失敗: " + errText(e)); }
    await reload();
  };
  bDel.onclick = async () => {
    if (!confirm(`既定値「${cur.name}」を削除しますか？`)) return;
    try { await send("DELETE", `/api/presets/${cur.id}`); presetSel = null; } catch (e) { alert("削除失敗: " + errText(e)); }
    await reload();
  };
  const list = el("div", { class: "preset-list" }, el("b", {}, "既定値"), el("ul", {}, presets.map(li)), el("div", { class: "btns" }, bNew, bRename, bDel));
  const form = el("form", { class: "preset-form" });
  const nameIn = el("input", { type: "text", style: "width:16em" });
  nameIn.value = cur ? cur.name : "";
  form.append(el("label", {}, "既定値の名前 ", nameIn), ...presetFields(schema, data), arrangeFieldset(data.arrange, () => live.later()));
  const msg = el("div", { class: "err" });
  form.append(el("button", { type: "submit" }, "保存"), msg);
  const collect = () => ({ ...readForm(form), arrange: data.arrange });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      const r = isNew ? await post("/api/presets", { name: nameIn.value, data: collect() }) : await send("PUT", `/api/presets/${cur.id}`, { name: nameIn.value, data: collect() });
      presetSel = r.id;
      await reload();
    } catch (e) { msg.className = "err"; msg.textContent = errText(e); if (cur) nameIn.value = cur.name; }
  });
  // 右: スロット図（容量表示つき・クリックで拡大）。入力のたびに保存前の値で描き直す
  const status = el("div", { class: "err", id: "live-status" });
  const box = el("div");
  const live = livePreview(collect, (lay) => {
    status.textContent = "";
    const [info, svg] = previewNodes(lay);
    const zoomBox = el("div", { class: "slot-zoom", id: "slot-zoom", onclick: () => zoomSvg(svg, info.textContent) }, svg, el("span", { class: "zbadge" }, "🔍 拡大"));
    box.replaceChildren(info, zoomBox, el("span", { class: "zhint" }, "クリックで拡大（ホイールで拡大縮小）"));
  }, (e) => { status.textContent = e.status === 422 ? "入力が不正なため、図は直前の設定のままです: " + errText(e) : "プレビュー失敗（図は直前のままです）: " + e.message; });
  form.addEventListener("input", live.later);
  form.addEventListener("change", live.later);
  const pv = el("div", { id: "live-preview" }, el("h3", {}, "面付けプレビュー（保存前の入力値で表示）"), status, box);
  root.replaceChildren(el("h2", {}, "設定作成"), el("div", { class: "preset-wrap" }, list, form, pv));
  await live.now();
}

// ---- PDF 作成 ----
let PDF = null; // 作成画面の状態。タブを切り替えても残す
const validRaw = (raw) => /^\d+$/.test(String(raw).trim()) && Number(raw) >= 1;
const fillCount = (nCards, cap) => (nCards <= 0 ? 0 : Math.max(1, Math.floor(cap / nCards)));
// スロット番号は行優先・1始まり。列優先は 1 列目の上から下へ（arrange.py の slot_order と同じ規則）
function slotOrder(n, cols, order) {
  if (order !== "col") return Array.from({ length: n }, (_, i) => i + 1);
  const rows = Math.ceil(n / cols), out = [];
  for (let c = 0; c < cols; c++) for (let r = 0; r < rows; r++) if (r * cols + c + 1 <= n) out.push(r * cols + c + 1);
  return out;
}
async function newPdf() {
  const presets = await api("/api/presets");
  const base = presets.find((p) => p.builtin) ?? presets[0];
  return { items: [], cards: {}, settings: structuredClone(base.data), presetId: base.id, slots: {}, manual: false, sel: null, adjust: null, saveMode: "new", single: 0, search: "", busy: false, msg: "", lay: null };
}
function addPdfItem(S, card, count) {
  S.cards[card.id] = card;
  if (!S.items.some((i) => i.card_id === card.id)) S.items.push({ card_id: card.id, raw: String(count) });
}
async function pdfFromCards(ids) {
  const S = await newPdf();
  const all = await api("/api/cards?reg=master");
  const per = S.settings.arrange.per_card ?? 1;
  for (const id of ids) { const c = all.find((x) => x.id === id); if (c) addPdfItem(S, c, per); }
  return S;
}
async function pdfFromAdjust(a) {
  const S = await newPdf();
  S.settings = structuredClone(a.settings);
  for (const c of a.cards) S.cards[c.id] = c;
  S.items = a.items.map((i) => ({ card_id: i.card_id, raw: String(i.count) }));
  S.slots = Object.fromEntries(Object.entries(a.slots).map(([k, v]) => [Number(k), v]));
  S.manual = null; // 最初のプレビューで、自動割当と同じなら自動、違えば個別差し替えとして扱う
  S.adjust = { sheet: a.sheet, has_snapshot: a.has_snapshot };
  S.saveMode = "new";
  return S;
}
async function renderPdf() {
  const root = $("#pdf");
  if (!PDF) PDF = await newPdf();
  const S = PDF;
  const [schema, presets, masters] = await Promise.all([api("/api/presets/schema"), api("/api/presets"), api("/api/cards?reg=master")]);
  for (const c of masters) S.cards[c.id] ??= c;
  const single = () => S.settings.arrange.group === "single";
  const cap = () => (S.lay ? S.lay.slots.length : 0);
  const count = (it) => (validRaw(it.raw) ? Number(it.raw) : 0);
  const autoAssign = () => {
    if (!S.lay) return {};
    const rows = single() ? S.items.slice(S.single, S.single + 1) : S.items;
    const seq = rows.flatMap((it) => Array(count(it)).fill(it.card_id));
    const out = {};
    slotOrder(cap(), S.lay.columns, S.settings.arrange.order).forEach((slot, k) => { if (k < seq.length) out[slot] = seq[k]; });
    return out;
  };
  const assign = () => (S.manual ? S.slots : autoAssign());
  const calc = () => {
    const counts = S.items.map(count);
    const total = single() ? Math.max(0, ...counts) : counts.reduce((a, b) => a + b, 0);
    const over = Math.max(0, total - cap());
    const invalid = S.items.some((it) => !validRaw(it.raw));
    return { total, over, invalid, ok: S.items.length > 0 && !invalid && total > 0 && over === 0 && !S.busy };
  };
  const applyFill = () => {
    if (S.settings.arrange.per_card !== null) return;
    const n = fillCount(S.items.length, cap());
    S.items.forEach((it) => (it.raw = String(n)));
  };
  const canOverwrite = () => !!S.adjust && !(single() && S.items.length > 1);
  const sync = () => { if (S.saveMode === "overwrite" && !canOverwrite()) S.saveMode = "new"; };

  const itemsBox = el("fieldset", {}, el("legend", {}, "使う名刺"));
  const summary = el("div");
  const candBox = el("div");
  const pvBox = el("div", { class: "pv", id: "pv" });
  const modeBox = el("fieldset", {}, el("legend", {}, "保存方法"));
  const createBtn = el("button", { type: "button", id: "create", style: "font-weight:bold;padding:6px 16px" }, S.adjust ? "保存して作成" : "作成");
  const msg = el("div", { class: "err", id: "pdf-msg" });
  const status = el("div", { class: "err", id: "pv-status" });

  const renderSummary = () => {
    const c = calc();
    summary.replaceChildren(el("div", { class: c.over ? "bad" : "" }, `合計 ${c.total} 枚 ／ 容量 ${cap()} 枚` + (c.over ? `（${c.over} 枚超過）` : "")));
    createBtn.disabled = !c.ok;
    createBtn.textContent = S.adjust ? "保存して作成" : "作成";
    const over = c.over ? el("span", { class: "bad", id: "over-msg" }, `  ${c.over} 枚超過のため作成できません（容量 ${cap()} 枚）`) : "";
    msg.replaceChildren(over);
    if (S.msg) msg.append(el("span", { class: "ok" }, S.msg));
    renderModes();
  };
  const renderModes = () => {
    sync();
    const r1 = el("input", { type: "radio", name: "sv" }), r2 = el("input", { type: "radio", name: "sv", disabled: !canOverwrite() });
    r1.checked = S.saveMode === "new"; r2.checked = S.saveMode === "overwrite";
    r1.onchange = () => (S.saveMode = "new"); r2.onchange = () => (S.saveMode = "overwrite");
    const sh = S.adjust?.sheet;
    modeBox.replaceChildren(el("legend", {}, "保存方法"),
      el("div", { class: "radio-row" }, el("label", {}, r1, "新規として保存"),
        el("label", {}, r2, sh ? `上書き保存（シート ${sh.id} の PDF を置き換える。印刷済みでも可）` : "上書き保存（調整元のシートがありません）")),
      single() && S.items.length > 1 ? el("div", { class: "desc" }, "1名刺1PDF で名刺が2種以上のときは新規保存のみです") : "");
  };
  const renderPreview = () => {
    if (!S.lay) return;
    const as = assign();
    const cards = Object.fromEntries(Object.entries(as).map(([slot, id]) => [slot, S.cards[id]]).filter(([, c]) => c));
    const [info, svg] = previewNodes(S.lay, { assign: cards, sel: S.sel });
    svg.id = "pv-svg";
    svg.onclick = (ev) => {
      const g = ev.target.closest("[data-slot]");
      if (g) { S.sel = Number(g.dataset.slot); renderPreview(); } else zoomSvg(svg, info.textContent);
    };
    const used = Object.keys(as).length;
    const parts = [el("h3", {}, "面付けプレビュー"),
      el("div", {}, `容量 ${cap()} 枚（${S.lay.columns} 列 × ${S.lay.rows} 行）／ 使用 ${used} 枚 ／ ${S.settings.arrange.order === "col" ? "列優先" : "行優先"}`), status, svg,
      el("div", { class: "hint" }, "クリックで拡大（ホイールで拡大縮小）・スロットをクリックで名刺を差し替え", " ", el("button", { type: "button", onclick: () => zoomSvg(svg, info.textContent) }, "🔍 拡大"))];
    if (single() && S.items.length > 1) {
      const sel = el("select", {}, S.items.map((it, i) => el("option", { value: i }, cardLabel(S.cards[it.card_id]))));
      sel.value = S.single;
      sel.onchange = () => { S.single = Number(sel.value); renderPreview(); };
      parts.splice(2, 0, el("label", {}, "プレビューする名刺 ", sel));
    }
    if (S.sel) {
      const cur = as[S.sel];
      const pick = el("select", {}, Object.values(S.cards).map((c) => el("option", { value: c.id }, cardLabel(c))), el("option", { value: "" }, "空にする"));
      pick.value = cur ?? "";
      const doReplace = () => {
        if (!S.manual) { S.slots = { ...autoAssign() }; S.manual = true; }
        if (pick.value === "") delete S.slots[S.sel]; else S.slots[S.sel] = Number(pick.value);
        renderPreview(); renderSummary();
      };
      const reset = () => { S.manual = false; S.slots = {}; renderPreview(); };
      parts.push(el("div", { class: "pan" }, `スロット ${S.sel} の名刺: ${cur ? cardLabel(S.cards[cur]) : "空き"}`, el("br"),
        el("label", {}, "差し替える名刺 ", pick), " ", el("button", { type: "button", onclick: doReplace }, "差し替える"), " ", el("button", { type: "button", onclick: reset }, "自動配置に戻す")));
    }
    pvBox.replaceChildren(...parts);
  };
  const itemRow = (it, i) => {
    const c = S.cards[it.card_id];
    const q = el("input", { type: "number", min: "1", style: "width:4.5em" });
    q.value = it.raw;
    q.addEventListener("input", () => {
      if (S.manual && !confirm("スロットの個別差し替えがあります。自動割当をやり直しますか？")) { q.value = it.raw; return; }
      if (S.manual) { S.manual = false; S.slots = {}; }
      it.raw = q.value;
      renderSummary(); renderPreview();
    });
    return el("div", { class: "ir" }, el("img", { src: fileUrl(c.image_path), loading: "lazy", alt: "" }),
      el("span", { class: "nm" }, cardLabel(c), c.reg === "deleted" ? "（マスタから削除済み）" : "", el("br"), el("small", {}, c.source_name ?? "")),
      el("label", {}, "枚数 ", q),
      el("button", { type: "button", onclick: () => { S.items.splice(i, 1); S.single = 0; changed(); } }, "削除"));
  };
  const renderItems = () => itemsBox.replaceChildren(el("legend", {}, "使う名刺"), ...S.items.map(itemRow), summary,
    el("div", { style: "margin-top:8px" }, el("label", {}, "マスタから追加", " ", search), candBox));
  const search = el("input", { type: "text", style: "width:14em" });
  search.value = S.search;
  const renderCand = () => {
    const q = S.search.trim().toLowerCase();
    const list = !q ? [] : masters.filter((c) => !S.items.some((i) => i.card_id === c.id) && [c.name ?? "", c.source_name ?? "", dateOf(c)].some((t) => t.toLowerCase().includes(q)));
    candBox.replaceChildren(...list.map((c) => el("div", { class: "ir" }, el("img", { src: fileUrl(c.image_path), loading: "lazy", alt: "" }),
      el("span", { class: "nm" }, cardLabel(c), el("br"), el("small", {}, c.source_name ?? "")),
      el("button", { type: "button", onclick: () => { addPdfItem(S, c, S.settings.arrange.per_card ?? 1); changed(); } }, "追加"))));
  };
  search.addEventListener("input", () => { S.search = search.value; renderCand(); });
  // 名刺の増減・並べ方の変更: 全部埋めを再計算し、手動の差し替えは捨てて自動割当に戻す
  const changed = () => {
    applyFill();
    if (S.manual) { S.manual = false; S.slots = {}; }
    renderItems(); renderCand(); renderSummary(); renderPreview();
  };

  // 左: 既定値・補正・面付け・並べ方
  const form = el("form", { class: "pf" });
  const pre = el("select", {}, presets.map((p) => el("option", { value: p.id }, p.name)));
  pre.value = S.presetId;
  const settingsBox = el("div");
  const collect = () => ({ ...readForm(form), correct: readForm(form).correct, layout: { ...S.settings.layout, ...(readForm(form).layout ?? {}) }, arrange: S.settings.arrange });
  const live = livePreview(() => ({ correct: collect().correct, layout: collect().layout, arrange: S.settings.arrange }), (lay) => {
    status.textContent = "";
    const first = !S.lay;
    S.lay = lay;
    if (S.manual === null) S.manual = JSON.stringify(Object.entries(autoAssign()).sort()) !== JSON.stringify(Object.entries(S.slots).map(([k, v]) => [k, v]).sort());
    if (first || S.settings.arrange.per_card === null) applyFill();
    renderItems(); renderSummary(); renderPreview();
  }, (e) => { status.textContent = e.status === 422 ? "入力が不正なため、図は直前の設定のままです: " + errText(e) : "プレビュー失敗（図は直前のままです）: " + e.message; });
  const buildSettings = () => {
    const opened = [...settingsBox.querySelectorAll(":scope > fieldset > details")].map((d) => d.open);
    const fs = presetFields(schema, S.settings).map((f, i) => {
      const [legend, ...rest] = f.children;
      f.replaceChildren(legend, el("details", { open: !!opened[i] }, el("summary", {}, "項目を表示"), rest));
      return f;
    });
    settingsBox.replaceChildren(...fs,arrangeFieldset(S.settings.arrange, () => { S.single = 0; if (S.lay) changed(); live.later(); }, "名刺を追加したときの枚数の初期値。名刺ごとに上の一覧で変えられる"));
  };
  pre.onchange = () => {
    const p = presets.find((x) => x.id === Number(pre.value));
    S.presetId = p.id; S.settings = structuredClone(p.data); S.slots = {}; S.manual = false;
    buildSettings(); live.now();
  };
  const savePreset = async (overwrite) => {
    const data = collect();
    try {
      if (overwrite) {
        const p = presets.find((x) => x.id === Number(pre.value));
        if (!confirm(`既定値「${p.name}」を現在の値で上書きしますか？`)) return;
        await send("PUT", `/api/presets/${p.id}`, { data });
      } else {
        const name = prompt("既定値の名前");
        if (name === null) return;
        const r = await post("/api/presets", { name, data });
        S.presetId = r.id;
      }
      S.settings = structuredClone(data); msg.textContent = "既定値を保存しました";
      await renderPdf();
    } catch (e) { alert("既定値の保存失敗: " + errText(e)); }
  };
  form.append(...(S.adjust ? [el("div", { class: "hint", id: "adjust-banner" },
    `履歴から調整中: ${S.adjust.sheet.job_id ? `ジョブ ${S.adjust.sheet.job_id} の` : ""}シート ${S.adjust.sheet.id}（${STATUS_LABEL[S.adjust.sheet.status] ?? S.adjust.sheet.status}）の名刺・値を読み込みました`,
    S.adjust.has_snapshot ? "" : el("div", {}, "作成時の設定は残っていません（補正・面付け・並べ方は既定値「既定」で補っています）"))] : []),
    itemsBox,
    el("fieldset", {}, el("legend", {}, "既定値"), el("label", {}, "既定値の読み込み ", pre), " ",
      el("button", { type: "button", onclick: () => savePreset(true) }, "上書き保存"), " ", el("button", { type: "button", onclick: () => savePreset(false) }, "別名で保存"),
      el("div", { class: "desc" }, "読み込むと下の補正・面付け・並べ方が置き換わる。変更後は「上書き保存」で選んだ既定値に、「別名で保存」で新しい既定値にする")),
    settingsBox, modeBox, createBtn, msg);
  form.addEventListener("input", (ev) => { if (ev.target.dataset?.key) live.later(); });
  form.addEventListener("change", (ev) => { if (ev.target.dataset?.key) live.later(); });
  buildSettings();
  createBtn.onclick = async () => {
    const c = calc();
    if (!c.ok) return;
    const overwrite = S.saveMode === "overwrite" && canOverwrite();
    if (overwrite) {
      const st = S.adjust.sheet.status;
      if (!confirm(`シート ${S.adjust.sheet.id} の PDF を置き換えます。${st === "sent" ? "印刷済みです。" : ""}よろしいですか？`)) return;
    }
    const body = { items: S.items.map((it) => ({ card_id: it.card_id, count: Number(it.raw) })), slots: S.manual ? S.slots : null, preset: { ...collect(), layout: collect().layout } };
    S.busy = true; S.msg = ""; renderSummary();
    try {
      const r = overwrite ? await send("PUT", `/api/sheets/${S.adjust.sheet.id}/pdf`, body) : await post("/api/pdf", body);
      S.msg = `作成しました（シート ${r.sheets.map((x) => "#" + x.id).join("・")}）`;
      if (!r.delivery.ok) alert("送信失敗: " + r.delivery.error);
    } catch (e) { alert("保存失敗: " + errText(e)); }
    S.busy = false; renderSummary();
  };
  root.replaceChildren(el("h2", {}, "PDF 作成"), el("div", { class: "pw" }, form, pvBox));
  renderItems(); renderCand(); renderSummary();
  await live.now();
}

show("history");
