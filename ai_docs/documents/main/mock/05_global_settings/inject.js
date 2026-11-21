async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"全体設定","ingest_button":"取込&作成","sections":["intake","detect","print","device"],"print_skip":["timing","duplicate_count"],"auto":{"legend":"フォルダ監視の自動取り込み","opts":["取り込みのみ","取込&作成"],"selected":"取込&作成","preset_label":"使う既定値","presets":["既定","名刺10面・名刺間トンボ","A4 2面・ライト"],"preset_selected":"既定","desc":"監視フォルダに画像が届いたときの動作。取込&作成は選んだ既定値で PDF も作る（取り込んだ名刺は登録待ちに入り、マスタには自動で登録しない）"},"save":"保存"};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.radio-row{display:flex;gap:16px;align-items:center;flex-wrap:wrap}.radio-row label{display:inline-flex;gap:4px;align-items:center;margin:4px 0}';
    document.head.append(st);
  }
  show('settings');
  await new Promise(r => setTimeout(r, 1500));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const [schema, cfg, info] = await Promise.all([api('/api/config/schema'), api('/api/config'), api('/api/info')]);
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const root = document.querySelector('#settings');
  root.replaceChildren(mk('h2', {}, '全体設定'));
  root.append(mk('div', { class: 'hint' }, mk('b', {}, 'iPrint&Scan 側で合わせる値'), mk('br'), `保存先: ${info.inbox_dir}`, mk('br'), '形式: PNG', mk('br'), `解像度: ${info.expected_dpi} dpi`));
  const form = mk('form');
  // 新規: フォルダ監視の自動取り込み
  const A = D.auto;
  const ra = mk('input', { type: 'radio', name: 'auto' }), rb = mk('input', { type: 'radio', name: 'auto' });
  (A.selected === A.opts[0] ? ra : rb).checked = true;
  const ps = mk('select', {}, ...A.presets.map((p) => mk('option', {}, p))); ps.value = A.preset_selected;
  form.append(mk('fieldset', {}, mk('legend', {}, A.legend), mk('div', { class: 'radio-row' }, mk('label', {}, ra, A.opts[0]), mk('label', {}, rb, A.opts[1], ' （', A.preset_label, ' ', ps, '）')), mk('div', { class: 'desc', style: 'color:#777;font-size:12px' }, A.desc)));
  for (const section of D.sections) {
    const sp = schema.properties[section];
    const def = resolve(schema, sp.$ref ?? sp.allOf[0].$ref);
    const fs = mk('fieldset', {}, mk('legend', {}, sp.title ?? section));
    for (const [key, prop] of Object.entries(def.properties)) { if (section === 'print' && D.print_skip.includes(key)) continue; fs.append(field(section, key, prop, cfg[section][key])); }
    if (section === 'print') fs.append(lpPicker(fs));
    form.append(fs);
  }
  form.append(mk('button', { type: 'button' }, D.save));
  root.append(form);
  await new Promise(r => setTimeout(r, 1200));
  const keys = (s) => form.querySelectorAll(`[data-section=${s}]`).length;
  return { fieldsets: form.querySelectorAll('fieldset').length, intake: keys('intake'), detect: keys('detect'), print: keys('print'), device: keys('device'), correctOrLayout: keys('correct') + keys('layout'), oldKeys: form.querySelectorAll('[data-key=timing],[data-key=duplicate_count]').length, autoRadios: 2, tabs: document.querySelectorAll('#tabs button').length };
}
