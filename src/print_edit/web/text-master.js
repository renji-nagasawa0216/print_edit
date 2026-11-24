// 個々の子の画像は、元の切り出し画像とPDFと同じ文字輪郭を重ねて表示する。
function textOverlayUrl(card) {
  return `/api/cards/${card.id}/text-overlay.svg`;
}

function cardThumbnail(card) {
  const base = el("img", { src: fileUrl(card.image_path), loading: "lazy", alt: "" });
  if (!card.parent_id) return base;
  return el("span", { class: "text-thumb" }, base,
    el("img", { class: "text-ink", src: textOverlayUrl(card), loading: "lazy", alt: "" }));
}

async function openTextMaster(card, reload) {
  if (document.querySelector(".text-editor")) return;
  const editing = Boolean(card.parent_id);
  const title = editing ? "文字を編集" : "文字入りマスタを作成";
  const dialog = el("dialog", { class: "text-editor", "aria-labelledby": "text-title" });
  const heading = el("h2", { id: "text-title" }, title);
  const error = el("p", { class: "err", role: "alert" });
  const button = (label, onclick, attrs = {}) => el("button", { type: "button", onclick, ...attrs }, label);
  const close = button("閉じる", () => dialog.close());
  const loading = el("p", { role: "status" }, "フォントを読み込み中…");
  const header = el("div", { class: "text-editor-head" }, heading, close);
  dialog.append(header, loading, error);
  document.body.append(dialog);
  let pending, timer, previewUrl, saving = false;
  dialog.addEventListener("cancel", (e) => { if (saving) e.preventDefault(); });
  dialog.addEventListener("close", () => {
    clearTimeout(timer);
    pending?.abort();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    dialog.remove();
  }, { once: true });
  dialog.showModal();
  let fonts, config;
  try {
    [fonts, config] = await Promise.all([api("/api/fonts"), api("/api/config")]);
  } catch (e) {
    loading.remove();
    error.textContent = "読み込み失敗: " + errText(e);
    return;
  }
  if (!dialog.open) return;
  loading.remove();
  if (!fonts.length) {
    error.textContent = "利用できるフォントがありません。データフォルダの fonts に TTF・OTF・TTC を追加してから開き直してください。";
    return;
  }
  const width = Math.max(config.detect.card_width_mm, config.detect.card_height_mm);
  const height = Math.min(config.detect.card_width_mm, config.detect.card_height_mm);
  const boxes = editing ? structuredClone(card.boxes) : [];
  const defaultFont = fonts.find(f => /^(Hiragino Sans W3|ヒラギノ角ゴシック W3|Noto Sans CJK JP( Regular)?)$/i.test(f.name)) ?? fonts[0];
  const round = (value) => Math.round(value * 100) / 100;
  function newBox() {
    return { text: "", x_mm: round(width * 0.08), y_mm: round(height * (0.12 + 0.13 * (boxes.length % 5))),
      width_mm: round(width * 0.75), size_pt: 12, font_id: defaultFont.id, align: "left", bold: false, gray: 0 };
  }
  if (!boxes.length) boxes.push(newBox());
  let selected = 0;
  const name = el("input", { type: "text", maxlength: 100, required: true });
  name.value = editing ? card.name : ((card.name || "名刺") + "（文字入り）").slice(0, 100);
  const ink = el("img", { class: "text-ink", alt: "" });
  ink.hidden = true;
  const handles = el("div", { class: "text-handles" });
  const stage = el("div", { class: "text-stage", "aria-label": "名刺プレビュー" },
    el("img", { class: "text-base", src: fileUrl(card.image_path), alt: "元の名刺" }), ink, handles);
  stage.style.aspectRatio = width + " / " + height;
  const form = el("form");
  form.onsubmit = (e) => { e.preventDefault(); save(); };
  const saveButton = el("button", { type: "submit" }, "保存");
  const previewError = el("div", { class: "err", role: "status" });
  const fields = el("fieldset", { class: "text-fields" });
  const controls = new Map();
  const picker = el("select", { onchange: () => selectBox(Number(picker.value)) });
  const add = button("ボックスを追加", () => { boxes.push(newBox()); selectBox(boxes.length - 1); queuePreview(); });
  const remove = button("ボックスを削除", () => {
    boxes.splice(selected, 1);
    selectBox(Math.min(selected, boxes.length - 1));
    queuePreview();
  });
  const group = el("div", { class: "text-box-select" }, el("label", {}, "編集するボックス", picker), add, remove);
  const previewPanel = el("div", { class: "text-preview-panel" }, stage,
    el("p", { class: "desc" }, "枠をドラッグして移動し、右端をドラッグして幅を変更できます。"), previewError);
  form.append(el("label", { class: "text-name" }, "マスタ名", name),
    el("div", { class: "text-columns" }, previewPanel, el("div", {}, group, fields)), saveButton);
  dialog.insertBefore(form, error);
  function queuePreview() {
    clearTimeout(timer);
    pending?.abort();
    previewError.textContent = "";
    const controller = new AbortController();
    pending = controller;
    timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/text-preview", { method: "POST", headers: { "Content-Type": "application/json" },
          signal: controller.signal, body: JSON.stringify({ boxes, width_mm: width, height_mm: height }) });
        if (!res.ok) throw Object.assign(new Error("HTTP " + res.status), { body: await res.json() });
        const blob = await res.blob();
        if (controller.signal.aborted || !dialog.open) return;
        const next = URL.createObjectURL(blob);
        ink.src = next;
        ink.hidden = false;
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        previewUrl = next;
      } catch (e) {
        if (!controller.signal.aborted) { previewError.textContent = "プレビュー失敗: " + errText(e); ink.hidden = true; }
      }
    }, 100);
  }
  function renderHandles() {
    handles.replaceChildren(...boxes.map((box, i) => {
      const handle = el("div", { class: "text-box-handle" + (selected === i ? " selected" : ""), "data-index": i });
      Object.assign(handle.style, { left: box.x_mm / width * 100 + "%", top: box.y_mm / height * 100 + "%",
        width: box.width_mm / width * 100 + "%", height: (box.size_pt * 25.4 / 72 * 1.25 / height) * 100 + "%" });
      if (i === selected) handle.append(el("span", { class: "text-width-handle" }));
      return handle;
    }));
  }
  function selectBox(index) {
    selected = index;
    picker.replaceChildren(...boxes.map((_, i) => el("option", { value: i }, "ボックス " + (i + 1))));
    picker.value = index;
    add.disabled = boxes.length >= 64;
    remove.disabled = boxes.length <= 1;
    const box = boxes[selected];
    controls.clear();
    fields.replaceChildren(el("legend", {}, "ボックス " + (selected + 1)));
    function field(key, label, input, numeric = false) {
      if (input.type === "checkbox") input.checked = box[key]; else input.value = box[key];
      controls.set(key, input);
      input.addEventListener("input", () => {
        if (!input.validity.valid) return;
        box[key] = input.type === "checkbox" ? input.checked : numeric ? input.valueAsNumber : input.value;
        renderHandles(); queuePreview();
      });
      return el("label", {}, label, input);
    }
    const num = (key, label, min, max, step = "any") =>
      field(key, label, el("input", { type: "number", min, max, step, required: true }), true);
    const face = el("select", {}, fonts.map(f => el("option", { value: f.id }, f.name)));
    if (!fonts.some(f => f.id === box.font_id)) face.append(el("option", { value: box.font_id }, "フォントが見つかりません"));
    const align = el("select", {}, [["left", "左揃え"], ["center", "中央揃え"], ["right", "右揃え"]]
      .map(([value, text]) => el("option", { value }, text)));
    // 回転・縦書きは将来対応。カラーの操作はまだ提供していない。
    fields.append(field("text", "文字", el("textarea", { rows: 2, maxlength: 2000 })),
      field("font_id", "フォント", face), el("div", { class: "text-field-grid" },
        num("x_mm", "左（mm）", 0, width), num("y_mm", "上（mm）", 0, height),
        num("width_mm", "幅（mm）", 0.01, width), num("size_pt", "文字サイズ（pt）", 1, 300),
        field("align", "揃え", align), num("gray", "濃淡（0 黒〜255 白）", 0, 255, 1),
        field("bold", "太字", el("input", { type: "checkbox" })),
        el("label", {}, "カラー", el("input", { type: "color", disabled: true }))));
    renderHandles();
  }
  let drag;
  stage.onpointerdown = (event) => {
    const handle = event.target.closest(".text-box-handle");
    if (!handle || event.button !== 0) return;
    const resize = event.target.classList.contains("text-width-handle");
    selectBox(Number(handle.dataset.index));
    drag = { pointer: event.pointerId, x: event.clientX, y: event.clientY, original: { ...boxes[selected] }, resize };
    stage.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  stage.onpointermove = (event) => {
    if (!drag || event.pointerId !== drag.pointer) return;
    const rect = stage.getBoundingClientRect();
    const dx = (event.clientX - drag.x) * width / rect.width;
    const dy = (event.clientY - drag.y) * height / rect.height;
    const box = boxes[selected];
    if (drag.resize) box.width_mm = round(Math.max(0.1, Math.min(width - box.x_mm, drag.original.width_mm + dx)));
    else {
      box.x_mm = round(Math.max(0, Math.min(width - box.width_mm, drag.original.x_mm + dx)));
      box.y_mm = round(Math.max(0, Math.min(height - 0.1, drag.original.y_mm + dy)));
    }
    for (const key of ["x_mm", "y_mm", "width_mm"]) controls.get(key).value = box[key];
    renderHandles(); queuePreview();
  };
  stage.onlostpointercapture = () => { drag = null; };
  async function save() {
    if (saving || !form.reportValidity()) return;
    saving = true;
    saveButton.disabled = close.disabled = true;
    error.textContent = "";
    try {
      await send(editing ? "PUT" : "POST", `/api/cards/${card.id}/${editing ? "text-master" : "text-masters"}`,
        { name: name.value.trim(), boxes });
    } catch (e) {
      error.textContent = "保存失敗: " + errText(e);
      saving = saveButton.disabled = close.disabled = false;
      return;
    }
    dialog.close();
    try { await reload(); } catch (e) { alert("一覧の更新失敗: " + errText(e)); }
  }
  selectBox(0); queuePreview();
  name.focus();
}
