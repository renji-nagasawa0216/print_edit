async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"印刷待ち","ingest_button":"取込&作成","rows":[{"id":6,"job":"20261112-120613-a8c617","at":"2026-11-12T12:06:13+09:00","cards":1,"pdf":"jobs/20261112-120613-a8c617/sheets/01.pdf","sel":true},{"id":9,"job":"20261112-120740-64d84f","at":"2026-11-12T12:07:41+09:00","cards":1,"pdf":"jobs/20261112-120740-64d84f/sheets/01.pdf","sel":true},{"id":10,"job":"20261112-120835-4e08cb","at":"2026-11-12T12:08:36+09:00","cards":1,"pdf":"jobs/20261112-120835-4e08cb/sheets/01.pdf","sel":true},{"id":11,"job":"20261112-120846-e6e573","at":"2026-11-12T12:08:47+09:00","cards":1,"pdf":"jobs/20261112-120846-e6e573/sheets/01.pdf","sel":false}],"confirm":{"msg":"3件を印刷します。よろしいですか","ok":"印刷する","cancel":"キャンセル"},"result":{"summary":"3件中 成功2件・失敗1件（失敗しても残りは続行しました。失敗したシートは印刷待ちに残っています）","lines":[[6,"ok","印刷しました"],[9,"ok","印刷しました"],[10,"ng","印刷に失敗しました: lp: プリンター part_queue に接続できません"]]}};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.bulkbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0 12px;padding:8px;background:#f7f7f7;border:1px solid #ddd}.card.sel{background:#fffbe8;border-color:#888}.card .pick{display:flex;align-items:center;gap:6px;margin:0 0 4px}.resbox{border:1px solid #ccc;padding:8px;margin-bottom:12px}.resbox li{margin:2px 0}.res-ng{color:#b00}.res-ok{color:#265c26}';
    document.head.append(st);
  }
  show('held');
  await new Promise(r => setTimeout(r, 1000));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  const root = document.querySelector('#held');
  const mk = (tg, attrs = {}, ...kids) => { const e = document.createElement(tg); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); kids.flat().forEach((c) => e.append(c instanceof Node ? c : document.createTextNode(c))); return e; };
  const nSel = D.rows.filter((r) => r.sel).length;
  const all = mk('label', { style: 'display:inline-flex;align-items:center;gap:6px;margin:0' }, mk('input', { type: 'checkbox', id: 'mock-all' }), '全選択');
  const bar = mk('div', { class: 'bulkbar' }, all,
    mk('button', { type: 'button', id: 'mock-bulk-print' }, `選んだものを印刷（${nSel}件）`),
    mk('button', { type: 'button', id: 'mock-bulk-discard' }, `選んだものを破棄（${nSel}件）`));
  const cards = D.rows.map((r) => {
    const c = mk('div', { class: 'card' + (r.sel ? ' sel' : ''), 'data-sheet': r.id },
      mk('label', { class: 'pick' }, mk('input', { type: 'checkbox', class: 'pick-cb' }), `選択 #${r.id}`),
      sheetImg(r.id), mk('br'),
      `#${r.id} ${r.job} ${r.at} カード${r.cards}枚 `, mk('a', { href: fileUrl(r.pdf), target: '_blank' }, 'PDF'), mk('br'),
      mk('button', { type: 'button' }, '印刷する'), ' ', mk('button', { type: 'button' }, '破棄'));
    c.querySelector('.pick-cb').checked = r.sel;
    return c;
  });
  root.replaceChildren(mk('h2', {}, '印刷待ち'), bar, ...cards);
  const cbs = [...root.querySelectorAll('.pick-cb')];
  document.querySelector('#mock-all').indeterminate = cbs.some((c) => c.checked) && !cbs.every((c) => c.checked);
  window.__mock = {
    confirm: () => {
      const ov = mk('div', { id: 'mock-dialog', style: 'position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:flex-start;justify-content:center;padding-top:120px;z-index:9' },
        mk('div', { style: 'background:#fff;border:1px solid #888;padding:16px;width:min(380px,80vw)' },
          mk('p', { style: 'margin:0 0 14px' }, D.confirm.msg),
          mk('div', { style: 'text-align:right' }, mk('button', { type: 'button' }, D.confirm.cancel), ' ', mk('button', { type: 'button', style: 'font-weight:bold' }, D.confirm.ok))));
      document.body.append(ov);
    },
    result: () => {
      const ul = mk('ul', { style: 'margin:6px 0 0;padding-left:20px' }, ...D.result.lines.map(([id, st, msg]) => mk('li', { class: st === 'ok' ? 'res-ok' : 'res-ng' }, `${st === 'ok' ? '成功' : '失敗'} #${id} ${msg}`)));
      const box = mk('div', { class: 'resbox', id: 'mock-result' }, mk('b', {}, '一括印刷の結果'), mk('div', {}, D.result.summary), ul);
      root.querySelector('h2').after(box);
      // 成功した 6・9 は印刷待ちから消え、失敗した 10 と未選択の 11 が残る
      root.querySelectorAll('.card').forEach((c) => { if (['6', '9'].includes(c.dataset.sheet)) c.remove(); else { c.classList.remove('sel'); c.querySelector('.pick-cb').checked = false; } });
      document.querySelector('#mock-all').checked = false; document.querySelector('#mock-all').indeterminate = false;
      document.querySelector('#mock-bulk-print').textContent = '選んだものを印刷（0件）';
      document.querySelector('#mock-bulk-discard').textContent = '選んだものを破棄（0件）';
    },
  };
  return { checkboxes: cbs.length, checked: cbs.filter((c) => c.checked).length, bulkLabels: [document.querySelector('#mock-bulk-print').textContent, document.querySelector('#mock-bulk-discard').textContent], hasAll: !!document.querySelector('#mock-all'), tabs: document.querySelectorAll('#tabs button').length };
}
