async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"PDF 作成","ingest_button":"取込&作成","cards":{"1":{"name":"山田 太郎","file":"scan_20261112_001.jpg","sheet":2},"2":{"name":"佐藤 花子","file":"scan_20261112_002.jpg","sheet":4},"3":{"name":"","file":"scan_20261114_001.jpg","sheet":5},"4":{"name":"鈴木 一郎","file":"scan_20261114_002.jpg","sheet":6},"5":{"name":"","file":"scan_20261117_001.jpg","sheet":7},"6":{"name":"高橋 美咲","file":"scan_20261117_002.jpg","sheet":9}},"presets":["既定","名刺10面・名刺間トンボ","A4 2面・ライト"],"base":{"items":[[1,5],[2,5]],"order":"行優先","sel":8,"preset":"既定","search":"20261114"},"over":{"items":[[1,8],[2,5]]},"col":{"order":"列優先"},"adjust":{"items":[[1,3],[4,2]],"preset":"名刺10面・名刺間トンボ","search":"20261117","banner":"履歴から調整中: ジョブ 20261112-120302-f0a1e7 のシート 1（印刷済み）の名刺・値を読み込みました","modes":["新規として保存","上書き保存（シート 1 の PDF を置き換える。印刷済みでも可）"],"confirm":"上書きを選ぶと「シート 1 の PDF を置き換えます。印刷済みです。よろしいですか？」と確認が出ます。","button":"保存して作成"},"texts":{"cards":"使う名刺","add":"マスタから追加","load":"既定値の読み込み","save_preset":"既定値として保存","preview":"面付けプレビュー","zhint":"クリックで拡大（ホイールで拡大縮小）","create":"作成"}};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.pw{display:flex;gap:24px;align-items:flex-start;flex-wrap:wrap}.pf{flex:1 1 420px;min-width:0}.pv{flex:0 1 400px;position:sticky;top:8px;min-width:0}.pv svg{width:100%;max-width:400px;height:auto;cursor:zoom-in;border:1px solid #888;display:block}.ir{display:flex;gap:8px;align-items:center;border-bottom:1px solid #ddd;padding:6px 0;flex-wrap:wrap}.ir img{width:64px;border:1px solid #aaa}.ir .nm{flex:1 1 140px;min-width:0}.bad{color:#c00;font-weight:bold}.pan{border:1px solid #06c;padding:8px;margin-top:8px;font-size:13px}.radio-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.radio-row label{display:inline-flex;gap:4px;align-items:center}@media(max-width:700px){.pv{position:static;flex:1 1 100%}}';
    document.head.append(st);
  }
  show('preview');
  await new Promise(r => setTimeout(r, 1500));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const [schema, cfg, lay] = await Promise.all([api('/api/config/schema'), api('/api/config'), api('/api/layout/preview')]);
  const thumb = (id) => new Promise((res) => { const im = new Image(); im.onload = () => { const c = document.createElement('canvas'); c.width = 360; c.height = 218; c.getContext('2d').drawImage(im, 165, 130, 1075, 650, 0, 0, 360, 218); res(c.toDataURL('image/jpeg', .8)); }; im.src = `/api/sheets/${id}/image.png`; });
  const th = {}; for (const [k, v] of Object.entries(D.cards)) th[k] = await thumb(v.sheet);
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const ns = 'http://www.w3.org/2000/svg';
  const sv = (t, a) => { const e = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) e.setAttribute(k, v); return e; };
  const S = { items: D.base.items, order: D.base.order, sel: D.base.sel, preset: D.base.preset, search: D.base.search, adjust: false };
  const nm = (id) => `#${id} ${D.cards[id].name || '（名前なし）'}`;
  const root = document.querySelector('#preview');
  const draw = () => {
    const seq = S.items.flatMap(([id, n]) => Array(n).fill(id));
    const cap = lay.capacity, over = Math.max(0, seq.length - cap), cols = lay.columns, rows = lay.rows;
    const L0 = lay.slots[0], slots = Array.from({ length: cap }, (_, i) => ({ index: i + 1, x: L0.x + (i % cols) * L0.w, y: L0.y + Math.floor(i / cols) * L0.h, w: L0.w, h: L0.h }));
    const at = {}; seq.slice(0, cap).forEach((id, k) => { const i = S.order === '列優先' ? (k % rows) * cols + Math.floor(k / rows) + 1 : k + 1; at[i] = id; });
    const svg = sv('svg', { viewBox: '0 0 210 297', id: 'pv-svg' });
    svg.append(sv('rect', { x: 0, y: 0, width: 210, height: 297, fill: '#fff' }));
    for (const s of slots) {
      const id = at[s.index];
      if (id) { svg.append(sv('image', { href: th[id], x: s.x, y: s.y, width: s.w, height: s.h, preserveAspectRatio: 'xMidYMid slice' }));
        svg.append(sv('rect', { x: s.x + s.w - 16, y: s.y + s.h - 7, width: 14, height: 5.5, fill: 'rgba(0,0,0,.65)' }));
        const t = sv('text', { x: s.x + s.w - 9, y: s.y + s.h - 3, 'text-anchor': 'middle', 'font-size': 3.8, fill: '#fff' }); t.textContent = `#${id}`; svg.append(t);
      } else { svg.append(sv('rect', { x: s.x, y: s.y, width: s.w, height: s.h, fill: '#f4f4f4', stroke: '#aaa', 'stroke-dasharray': '2' })); const t = sv('text', { x: s.x + s.w / 2, y: s.y + s.h / 2, 'text-anchor': 'middle', 'font-size': 5, fill: '#888' }); t.textContent = '空き'; svg.append(t); }
      svg.append(sv('circle', { cx: s.x + 4.5, cy: s.y + 4.5, r: 3.6, fill: '#333' }));
      const t = sv('text', { x: s.x + 4.5, y: s.y + 6, 'text-anchor': 'middle', 'font-size': 4.4, fill: '#fff' }); t.textContent = s.index; svg.append(t);
      if (S.sel === s.index) svg.append(sv('rect', { x: s.x, y: s.y, width: s.w, height: s.h, fill: 'none', stroke: '#06c', 'stroke-width': 1.4 }));
    }
    // 左: 名刺・既定値・フォーム
    const cand = Object.keys(D.cards).filter((k) => D.cards[k].file.includes(S.search) && !S.items.some(([i]) => i == k));
    const items = mk('fieldset', {}, mk('legend', {}, D.texts.cards), ...S.items.map(([id, n]) => mk('div', { class: 'ir' }, mk('img', { src: th[id] }), mk('span', { class: 'nm' }, nm(id), mk('br'), mk('small', {}, D.cards[id].file)), mk('label', {}, '枚数 ', Object.assign(mk('input', { type: 'number', min: '1', style: 'width:4.5em' }), { value: n })), mk('button', { type: 'button' }, '削除'))),
      mk('div', { class: bad(over) }, `合計 ${seq.length} 枚 ／ 容量 ${cap} 枚` + (over ? `（${over} 枚超過）` : '')),
      mk('div', { style: 'margin-top:8px' }, mk('label', {}, D.texts.add + ' ', Object.assign(mk('input', { type: 'text', style: 'width:14em' }), { value: S.search })), ...cand.map((k) => mk('div', { class: 'ir' }, mk('img', { src: th[k] }), mk('span', { class: 'nm' }, nm(k), mk('br'), mk('small', {}, D.cards[k].file)), mk('button', { type: 'button' }, '追加')))));
    const pre = mk('select', {}, ...D.presets.map((p) => mk('option', {}, p))); pre.value = S.preset;
    const presets = mk('fieldset', {}, mk('legend', {}, '既定値'), mk('label', {}, D.texts.load + ' ', pre), ' ', mk('button', { type: 'button' }, D.texts.save_preset), mk('div', { class: 'desc' }, '読み込むと下の補正・面付け・並べ方が置き換わる。変更後は「既定値として保存」で選んだ既定値に上書きする'));
    const form = mk('form', { class: 'pf' }, ...(S.adjust ? [mk('div', { class: 'hint' }, D.adjust.banner)] : []), items, presets);
    for (const [section, label] of [['correct', '補正'], ['layout', '面付け']]) {
      const sp = schema.properties[section]; const def = resolve(schema, sp.$ref ?? sp.allOf[0].$ref);
      const fs = mk('fieldset', {}, mk('legend', {}, label));
      for (const [key, prop] of Object.entries(def.properties)) { if (section === 'layout' && key === 'cards_per_sheet') continue; fs.append(field(section, key, prop, cfg[section][key])); }
      form.append(fs);
    }
    const grp = mk('select', {}, mk('option', {}, '1名刺1PDF'), mk('option', {}, '複数名刺1PDF')); grp.value = '複数名刺1PDF';
    const ord = mk('select', {}, mk('option', {}, '行優先'), mk('option', {}, '列優先')); ord.value = S.order;
    const r1 = mk('input', { type: 'radio', name: 'pc' }); r1.checked = true;
    form.append(mk('fieldset', {}, mk('legend', {}, '並べ方'), mk('label', {}, 'まとめ方 ', grp), mk('div', {}, '1名刺あたりの枚数', mk('div', { class: 'radio-row' }, mk('label', {}, r1, '数値 ', Object.assign(mk('input', { type: 'number', style: 'width:5em' }), { value: 2 }), ' 枚'), mk('label', {}, mk('input', { type: 'radio', name: 'pc' }), '全部埋める')), mk('span', { class: 'desc' }, '名刺を追加したときの枚数の初期値。名刺ごとに上の一覧で変えられる')), mk('label', {}, '並べ順 ', ord, mk('span', { class: 'desc' }, '行優先は左から右へ、列優先は上から下へ並べる'))));
    if (S.adjust) { const rs = D.adjust.modes.map((m, i) => { const r = mk('input', { type: 'radio', name: 'sv' }); r.checked = i === 0; return mk('label', {}, r, m); }); form.append(mk('fieldset', {}, mk('legend', {}, '保存方法'), mk('div', { class: 'radio-row' }, ...rs), mk('div', { class: 'desc' }, D.adjust.confirm))); }
    const go = mk('button', { type: 'button', id: 'create', style: 'font-weight:bold;padding:6px 16px' }, S.adjust ? D.adjust.button : D.texts.create); go.disabled = over > 0;
    form.append(go, over ? mk('span', { class: 'bad', id: 'over-msg' }, `  ${over} 枚超過のため作成できません（容量 ${cap} 枚）`) : '');
    // 右: プレビュー
    const pan = mk('div', { class: 'pan' }, `スロット ${S.sel} の名刺: ${at[S.sel] ? nm(at[S.sel]) : '空き'}`, mk('br'), mk('label', {}, '差し替える名刺 ', mk('select', {}, ...Object.keys(D.cards).map((k) => mk('option', {}, nm(k))), mk('option', {}, '空にする'))), ' ', mk('button', { type: 'button' }, '差し替える'), ' ', mk('button', { type: 'button' }, '自動配置に戻す'));
    const pv = mk('div', { class: 'pv', id: 'pv' }, mk('h3', {}, D.texts.preview), mk('div', {}, `容量 ${cap} 枚（${cols} 列 × ${rows} 行）／ 使用 ${Math.min(seq.length, cap)} 枚 ／ ${S.order}`), svg, mk('div', { class: 'hint' }, D.texts.zhint + '・スロットをクリックで名刺を差し替え'), S.sel ? pan : '');
    root.replaceChildren(mk('h2', {}, 'PDF 作成'), mk('div', { class: 'pw' }, form, pv));
  };
  const bad = (o) => (o ? 'bad' : '');
  draw();
  const zoom = () => { const big = document.querySelector('#pv-svg').cloneNode(true); big.style.cssText = 'width:min(calc(100vw - 24px),calc(86vh * 0.707));height:auto;max-width:none;background:#fff;cursor:zoom-out';
    document.body.append(mk('div', { id: 'mock-zoom', style: 'position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:9;display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px;box-sizing:border-box;overflow:auto' }, mk('div', { style: 'color:#fff;display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:center;font-size:13px' }, mk('button', { type: 'button' }, '＋'), mk('button', { type: 'button' }, '－'), mk('button', { type: 'button' }, '閉じる'), 'ホイールで拡大縮小・クリックか Esc で閉じる'), big)); };
  window.__mock = { zoom, col: () => { S.order = D.col.order; draw(); }, over: () => { S.items = D.over.items; draw(); }, adjust: () => { Object.assign(S, { items: D.adjust.items, preset: D.adjust.preset, search: D.adjust.search, adjust: true, sel: null }); draw(); } };
  return { rows: document.querySelectorAll('.ir').length, slots: document.querySelectorAll('#pv-svg image').length, tabs: document.querySelectorAll('#tabs button').length, create: document.querySelector('#create').disabled };
}
