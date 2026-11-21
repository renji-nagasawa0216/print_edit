async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"設定作成","ingest_button":"取込&作成","presets":[{"name":"既定","note":"自動作成","selected":true},{"name":"名刺10面・名刺間トンボ","note":""},{"name":"A4 2面・ライト","note":""}],"list_buttons":["新規","名前を変更","削除"],"sections":{"correct":"補正","layout":"面付け","layout_skip":["cards_per_sheet"]},"arrange":{"title":"並べ方","group":{"label":"まとめ方","opts":["1名刺1PDF","複数名刺1PDF"],"selected":"複数名刺1PDF"},"per_card":{"label":"1名刺あたりの枚数","num":2,"fill":"全部埋める","mode":"数値"},"order":{"label":"並べ順","opts":["行優先","列優先"],"selected":"行優先"}},"preview":{"title":"面付けプレビュー（保存前の入力値で表示）","hint":"クリックで拡大（ホイールで拡大縮小）"},"zoom":{"hint":"ホイールで拡大縮小・クリックか Esc で閉じる","buttons":["＋","－","閉じる"]},"save":"保存"};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.preset-wrap{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}.preset-list{flex:0 0 220px;border:1px solid #ccc;padding:8px}.preset-list ul{list-style:none;margin:0 0 8px;padding:0}.preset-list li{padding:6px 8px;border:1px solid transparent;cursor:pointer}.preset-list li.on{background:#333;color:#fff}.preset-list li small{opacity:.7;margin-left:6px}.preset-list .btns button{margin:2px 2px 0 0}.preset-form{flex:1 1 380px;min-width:0}.slot-zoom{cursor:zoom-in;position:relative;display:inline-block}.slot-zoom .zhint{display:block;font-size:12px;color:#555;margin-top:4px}.slot-zoom .zbadge{position:absolute;right:6px;top:6px;background:#333;color:#fff;font-size:12px;padding:2px 6px;border-radius:8px}.radio-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.radio-row label{display:inline-flex;gap:4px;align-items:center;margin:4px 0}.preset-wrap #live-preview{flex:0 1 380px}@media(max-width:700px){.preset-list{flex:1 1 100%}.preset-wrap #live-preview{position:static;max-width:100%;flex:1 1 100%}}';
    document.head.append(st);
  }
  show('settings');
  await new Promise(r => setTimeout(r, 1500));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const [schema, cfg, lay] = await Promise.all([api('/api/config/schema'), api('/api/config'), api('/api/layout/preview')]);
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const root = document.querySelector('#settings');
  // 左: 既定値の一覧
  const sel = D.presets.find((p) => p.selected);
  const list = mk('div', { class: 'preset-list' }, mk('b', {}, '既定値'),
    mk('ul', {}, ...D.presets.map((p) => mk('li', { class: p.selected ? 'on' : '' }, p.name, p.note ? mk('small', {}, `（${p.note}）`) : ''))),
    mk('div', { class: 'btns' }, ...D.list_buttons.map((t) => { const b = mk('button', { type: 'button' }, t); if (t === '削除' && sel.note) b.disabled = true; return b; })));
  // 中: 編集フォーム（既存「設定」の補正・面付けを流用）
  const form = mk('form', { class: 'preset-form' });
  form.append(mk('label', {}, '既定値の名前 ', Object.assign(mk('input', { type: 'text', style: 'width:16em' }), { value: sel.name })));
  for (const section of ['correct', 'layout']) {
    const sp = schema.properties[section];
    const def = resolve(schema, sp.$ref ?? sp.allOf[0].$ref);
    const fs = mk('fieldset', {}, mk('legend', {}, D.sections[section]));
    for (const [key, prop] of Object.entries(def.properties)) { if (section === 'layout' && D.sections.layout_skip.includes(key)) continue; fs.append(field(section, key, prop, cfg[section][key])); }
    form.append(fs);
  }
  const A = D.arrange;
  const grp = mk('select', {}, ...A.group.opts.map((o) => mk('option', {}, o))); grp.value = A.group.selected;
  const ord = mk('select', {}, ...A.order.opts.map((o) => mk('option', {}, o))); ord.value = A.order.selected;
  const num = Object.assign(mk('input', { type: 'number', min: '1', style: 'width:5em' }), { value: A.per_card.num });
  const r1 = mk('input', { type: 'radio', name: 'pc' }); r1.checked = true;
  const r2 = mk('input', { type: 'radio', name: 'pc' });
  form.append(mk('fieldset', {}, mk('legend', {}, A.title),
    mk('label', {}, A.group.label, ' ', grp, mk('span', { class: 'desc' }, '複数名刺1PDF は別々の名刺を同じ PDF に並べる')),
    mk('div', {}, A.per_card.label, mk('div', { class: 'radio-row' }, mk('label', {}, r1, '数値 ', num, ' 枚'), mk('label', {}, r2, A.per_card.fill))),
    mk('label', {}, A.order.label, ' ', ord, mk('span', { class: 'desc' }, '行優先は左から右へ、列優先は上から下へ並べる'))));
  form.append(mk('button', { type: 'button' }, D.save));
  // 右: 従来のスロット図（容量表示つき）。クリックで拡大
  const [info, svg] = previewNodes(lay);
  const zoomBox = mk('div', { class: 'slot-zoom', id: 'slot-zoom' }, svg, mk('span', { class: 'zbadge' }, '🔍 拡大'));
  const live = mk('div', { id: 'live-preview' }, mk('h3', {}, D.preview.title), info, zoomBox, mk('span', { class: 'zhint' }, D.preview.hint));
  root.replaceChildren(mk('h2', {}, '設定作成'), mk('div', { class: 'preset-wrap' }, list, form, live));
  window.__mock = {
    zoom: () => {
      const big = svg.cloneNode(true); big.style.cssText = 'max-height:none;max-width:none;height:88vh;width:auto;background:#fff;border:1px solid #888';
      const ov = mk('div', { id: 'mock-zoom', style: 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9;display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px;box-sizing:border-box;overflow:auto' },
        mk('div', { style: 'color:#fff;display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:center' }, ...D.zoom.buttons.map((t) => mk('button', { type: 'button' }, t)), D.zoom.hint, `  ${info.textContent}`),
        big);
      document.body.append(ov);
    },
  };
  return { presets: list.querySelectorAll('li').length, listButtons: list.querySelectorAll('button').length, correctFields: form.querySelectorAll('[data-section=correct]').length, layoutFields: form.querySelectorAll('[data-section=layout]').length, arrangeSelects: 2, oldKeys: form.querySelectorAll('[data-key=timing],[data-key=duplicate_count],[data-key=cards_per_sheet]').length, svg: !!svg, tabs: document.querySelectorAll('#tabs button').length };
}
