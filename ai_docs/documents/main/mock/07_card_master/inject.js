async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"名刺マスタ","ingest_button":"取込&作成","title":"名刺マスタ","search":{"label":"検索","placeholder":"名前・元ファイル名・取込日（部分一致）","value":""},"count":"8件中 8件を表示","bar":{"pdf":"PDF 作成（{n}件）","clear":"選択を解除"},"edit":"名前を保存","delete":"マスタから削除","noname":"名前を入力","cards":[{"id":1,"name":"山田 太郎","file":"scan_20261112_001.jpg","date":"2026-11-12","sheet":2,"sel":true},{"id":2,"name":"佐藤 花子","file":"scan_20261112_002.jpg","date":"2026-11-12","sheet":4},{"id":3,"name":"","file":"scan_20261114_001.jpg","date":"2026-11-14","sheet":5},{"id":4,"name":"鈴木 一郎","file":"scan_20261114_002.jpg","date":"2026-11-14","sheet":6,"sel":true},{"id":5,"name":"","file":"scan_20261117_001.jpg","date":"2026-11-17","sheet":7},{"id":6,"name":"高橋 美咲","file":"scan_20261117_002.jpg","date":"2026-11-17","sheet":9},{"id":7,"name":"田中 健","file":"scan_20261118_001.jpg","date":"2026-11-18","sheet":10},{"id":8,"name":"","file":"scan_20261119_001.jpg","date":"2026-11-19","sheet":11}]};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}.ccard{display:flex;gap:8px;border:1px solid #ccc;padding:8px;align-items:flex-start}.ccard.on{border-color:#333;background:#f3f3f3}.ccard img{width:120px;height:auto;border:1px solid #aaa;flex:none}.ccard .info{flex:1;min-width:0;font-size:13px;word-break:break-all}.ccard .info div{margin:4px 0}.ccard input[type=text]{width:100%;box-sizing:border-box}.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}';
    document.head.append(st);
  }
  show('preview');
  await new Promise(r => setTimeout(r, 800));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const thumb = (id) => new Promise((res) => { const im = new Image(); im.onload = () => { const c = document.createElement('canvas'); c.width = 360; c.height = 218; c.getContext('2d').drawImage(im, 165, 130, 1075, 650, 0, 0, 360, 218); res(c.toDataURL('image/jpeg', .8)); }; im.src = `/api/sheets/${id}/image.png`; });
  const th = await Promise.all(D.cards.map((c) => thumb(c.sheet)));
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const cb = (on) => { const i = mk('input', { type: 'checkbox' }); i.checked = !!on; return i; };
  const n = D.cards.filter((c) => c.sel).length;
  const root = document.querySelector('#preview');
  root.replaceChildren(mk('h2', {}, D.title),
    mk('div', { class: 'bar' }, mk('label', {}, D.search.label + ' ', Object.assign(mk('input', { type: 'text', placeholder: D.search.placeholder, style: 'width:22em;max-width:70vw' }), { value: D.search.value })), mk('span', { class: 'hint' }, D.count)),
    mk('div', { class: 'bar' }, mk('button', { type: 'button', style: 'font-weight:bold' }, D.bar.pdf.replace('{n}', n)), mk('button', { type: 'button' }, D.bar.clear)),
    mk('div', { class: 'cgrid', id: 'master' }, ...D.cards.map((c, i) => mk('div', { class: 'ccard' + (c.sel ? ' on' : '') }, cb(c.sel), mk('img', { src: th[i] }),
      mk('div', { class: 'info' }, mk('div', {}, `#${c.id}`), mk('div', {}, Object.assign(mk('input', { type: 'text', placeholder: D.noname }), { value: c.name }), mk('button', { type: 'button' }, D.edit)), mk('div', {}, c.file), mk('div', {}, `取込日 ${c.date}`), mk('div', {}, mk('button', { type: 'button' }, D.delete)))))));
  return { cards: document.querySelectorAll('#master .ccard').length, checked: document.querySelectorAll('#master input[type=checkbox]:checked').length, named: [...document.querySelectorAll('#master input[type=text]')].filter((i) => i.value).length, tabs: document.querySelectorAll('#tabs button').length };
}
