async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"取り込み","ingest_button":"取込&作成","watch":{"title":"取り込み","button":"画像を選んで取り込む","state":"フォルダ監視: 稼働中","folder":"~/Scans/inbox","last":"最終取り込み 2026-11-20 09:42","pending":"未取り込み 0 件"},"queue":{"title":"登録待ち","count":6,"all":"すべて選択","bulk_ok":"選んだものを登録（{n}件）","bulk_discard":"選んだものを破棄（{n}件）","one_ok":"マスタに登録","one_discard":"破棄","note":"取込&作成で PDF に使った名刺も、登録または破棄するまでここに残ります。","checked":[0,1]},"cards":[{"file":"scan_20261120_003.jpg","date":"2026-11-20","badge":"取込&作成で使用済み","sheet":2},{"file":"scan_20261120_002.jpg","date":"2026-11-20","badge":"取込&作成で使用済み","sheet":4},{"file":"scan_20261120_001.jpg","date":"2026-11-20","badge":"","sheet":5},{"file":"scan_20261117_004.jpg","date":"2026-11-17","badge":"","sheet":6},{"file":"scan_20261114_003.jpg","date":"2026-11-14","badge":"移行分","sheet":7},{"file":"scan_20261114_002.jpg","date":"2026-11-14","badge":"移行分","sheet":9}]};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}.ccard{display:flex;gap:8px;border:1px solid #ccc;padding:8px;align-items:flex-start}.ccard.on{border-color:#333;background:#f3f3f3}.ccard img{width:120px;height:auto;border:1px solid #aaa;flex:none}.ccard .info{flex:1;min-width:0;font-size:13px;word-break:break-all}.ccard .info div{margin:2px 0}.badge{display:inline-block;background:#333;color:#fff;font-size:11px;padding:1px 6px;border-radius:8px}.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0}';
    document.head.append(st);
  }
  show('preview');
  await new Promise(r => setTimeout(r, 800));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const thumb = (id) => new Promise((res) => { const im = new Image(); im.onload = () => { const c = document.createElement('canvas'); c.width = 360; c.height = 218; c.getContext('2d').drawImage(im, 165, 130, 1075, 650, 0, 0, 360, 218); res(c.toDataURL('image/jpeg', .8)); }; im.src = `/api/sheets/${id}/image.png`; });
  const th = await Promise.all(D.cards.map((c) => thumb(c.sheet)));
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const n = D.queue.checked.length, W = D.watch, Q = D.queue;
  const cb = (on) => { const i = mk('input', { type: 'checkbox' }); i.checked = on; return i; };
  const root = document.querySelector('#preview');
  root.replaceChildren(mk('h2', {}, W.title),
    mk('fieldset', {}, mk('legend', {}, 'スキャン画像'), mk('div', { class: 'bar' }, mk('button', { type: 'button' }, W.button), mk('span', {}, W.state), mk('code', {}, W.folder)), mk('div', { class: 'hint' }, `${W.last} ／ ${W.pending}`)),
    mk('h3', {}, `${Q.title}（${Q.count}件）`),
    mk('div', { class: 'bar' }, mk('label', {}, cb(false), Q.all), mk('button', { type: 'button' }, Q.bulk_ok.replace('{n}', n)), mk('button', { type: 'button' }, Q.bulk_discard.replace('{n}', n))),
    mk('div', { class: 'hint' }, Q.note),
    mk('div', { class: 'cgrid', id: 'queue' }, ...D.cards.map((c, i) => mk('div', { class: 'ccard' + (Q.checked.includes(i) ? ' on' : '') }, cb(Q.checked.includes(i)), mk('img', { src: th[i] }),
      mk('div', { class: 'info' }, mk('div', {}, c.file), mk('div', {}, `取込日 ${c.date}`), c.badge ? mk('div', {}, mk('span', { class: 'badge' }, c.badge)) : '', mk('div', {}, mk('button', { type: 'button' }, Q.one_ok), ' ', mk('button', { type: 'button' }, Q.one_discard)))))));
  return { cards: document.querySelectorAll('#queue .ccard').length, checked: document.querySelectorAll('#queue input:checked').length, imgs: [...document.querySelectorAll('#queue img')].every((i) => i.src.startsWith('data:')), tabs: document.querySelectorAll('#tabs button').length };
}
