const $ = (s) => document.querySelector(s);
const api = async (path, opt) => {
  const r = await fetch(path, opt);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status, body });
  return body;
};
const post = (p) => api(p, { method: "POST" });
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k.startsWith("on") ? (e[k] = v) : e.setAttribute(k, v);
  for (const c of kids.flat()) e.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return e;
};
const tag = (s) => el("span", { class: `tag ${s}` }, s);
const fileUrl = (p) => "/files/" + p;

// ---- タブ ----
const views = { history: renderHistory, review: renderReview, settings: renderSettings, preview: renderPreview };
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => show(b.dataset.tab))
);
function show(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  for (const k of Object.keys(views)) $("#" + k).hidden = k !== name;
  views[name]().catch((e) => ($("#" + name).textContent = "読み込み失敗: " + e.message));
}
$("#ingest-btn").addEventListener("click", async () => {
  const r = await post("/api/ingest");
  alert(`${r.length} 件処理しました`);
  show(document.querySelector("#tabs .active").dataset.tab);
});

// ---- 履歴 ----
async function renderHistory() {
  const root = $("#history");
  const jobs = await api("/api/jobs");
  root.replaceChildren(el("h2", {}, "履歴"));
  if (!jobs.length) root.append("ジョブはありません");
  for (const j of jobs) {
    const box = el("div", { class: "job" });
    box.append(el("div", {}, `${j.id} `, tag(j.status), ` ${j.source_name} / ${j.dpi ?? "-"}dpi / カード${j.card_count} シート${j.sheet_count} `, j.warnings.join(",")));
    const detail = el("div");
    box.append(el("button", { onclick: async () => {
      const d = await api("/api/jobs/" + j.id);
      detail.replaceChildren(
        el("div", { class: "row" },
          el("div", {}, "原画像", el("br"), el("img", { src: fileUrl(`jobs/${j.id}/source.png`) })),
          d.cards.map((c) => el("div", { class: "card" }, el("img", { src: fileUrl(c.image_path) }), el("br"), `#${c.idx} `, tag(c.status)))),
        d.sheets.map((s) => el("div", {}, el("a", { href: fileUrl(s.pdf_path), target: "_blank" }, s.pdf_path), " ", tag(s.status), s.error ?? ""))
      );
    } }, "詳細"), " ",
    el("button", { onclick: async () => {
      try { await post(`/api/jobs/${j.id}/reprint`); alert("再送しました"); }
      catch (e) { alert("再印刷失敗: " + (e.body?.detail ?? e.message)); }
    } }, "再印刷"), detail);
    root.append(box);
  }
}

// ---- 要確認 ----
async function renderReview(notice = "") {
  const root = $("#review");
  const cards = await api("/api/cards?status=review");
  root.replaceChildren(el("h2", {}, "要確認"));
  if (notice) root.append(el("div", { class: "error", id: "review-notice" }, notice));
  if (!cards.length) root.append("要確認のカードはありません");
  const act = (c, op) => async () => {
    const r = await post(`/api/cards/${c.id}/${op}`);
    await renderReview(r.delivery && !r.delivery.ok ? `承認しましたが出力に失敗しました: ${r.delivery.error}` : "");
  };
  for (const c of cards) {
    root.append(el("div", { class: "card" },
      el("img", { src: fileUrl(c.image_path), style: "max-width:320px" }), el("br"),
      `${c.job_id} #${c.idx} ${c.long_mm}x${c.short_mm}mm `, c.reasons.join(","), el("br"),
      el("button", { onclick: act(c, "approve") }, "承認"), " ",
      el("button", { onclick: act(c, "rotate") }, "180度回転"), " ",
      el("button", { onclick: act(c, "discard") }, "破棄")));
  }
}

// ---- 設定（JSON Schema から生成） ----
const resolve = (schema, ref) => schema.$defs[ref.split("/").pop()];
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
async function renderSettings() {
  const root = $("#settings");
  const [schema, cfg, info] = await Promise.all([api("/api/config/schema"), api("/api/config"), api("/api/info")]);
  root.replaceChildren(el("h2", {}, "設定"));
  root.append(el("div", { class: "hint" }, el("b", {}, "iPrint&Scan 側で合わせる値"), el("br"),
    `保存先: ${info.inbox_dir}`, el("br"), "形式: PNG", el("br"), `解像度: ${info.expected_dpi} dpi`));
  const form = el("form");
  for (const [section, sp] of Object.entries(schema.properties)) {
    const def = resolve(schema, sp.$ref ?? sp.allOf[0].$ref);
    const fs = el("fieldset", {}, el("legend", {}, sp.title ?? section));
    for (const [key, prop] of Object.entries(def.properties)) fs.append(field(section, key, prop, cfg[section][key]));
    form.append(fs);
  }
  const msg = el("div", { class: "err" });
  form.append(el("button", { type: "submit" }, "保存"), msg);
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(readForm(form)) }); msg.textContent = "保存しました"; msg.className = ""; }
    catch (e) { msg.className = "err"; msg.textContent = e.status === 422 ? e.body.detail.map((d) => `${d.loc.join(".")}: ${d.msg}`).join(" / ") : e.message; }
  });
  root.append(form);
}

// ---- 面付けプレビュー ----
async function renderPreview() {
  const root = $("#preview");
  const [cap, lay] = await Promise.all([api("/api/capacity"), api("/api/layout/preview")]);
  root.replaceChildren(el("h2", {}, "面付けプレビュー"),
    el("div", {}, `容量 ${cap.capacity} 枚（${cap.columns} 列 × ${cap.rows} 行、${cap.card_rotated ? "縦置き" : "横置き"}）`));
  const [pw, ph] = lay.paper_mm, [x, y, w, h] = lay.printable_mm;
  const ns = "http://www.w3.org/2000/svg";
  const n = (t, a) => { const e = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
  const svg = n("svg", { viewBox: `0 0 ${pw} ${ph}`, width: pw * 2.5 });
  svg.append(n("rect", { x, y, width: w, height: h, fill: "none", stroke: "#c00", "stroke-dasharray": "2" }));
  for (const s of lay.slots) {
    svg.append(n("rect", { x: s.x, y: s.y, width: s.w, height: s.h, fill: "#dfe9f7", stroke: "#357" , "stroke-width": 0.3}));
    const t = n("text", { x: s.x + s.w / 2, y: s.y + s.h / 2, "text-anchor": "middle", "font-size": 6 }); t.textContent = s.card; svg.append(t);
  }
  for (const m of lay.marks) svg.append(n("line", { x1: m.x1, y1: m.y1, x2: m.x2, y2: m.y2, stroke: "#000", "stroke-width": 0.2 }));
  root.append(svg);
}

show("history");
