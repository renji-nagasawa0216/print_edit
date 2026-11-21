async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"履歴","ingest_button":"取込&作成","job_id":"20261112-120922-538998","sheet_buttons":["再印刷","調整する"]};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}.sheet-line{margin:6px 0;padding:6px;border:1px solid #ddd}.sheet-line button{margin-left:6px}';
    document.head.append(st);
  }
  show('history');
  await new Promise(r => setTimeout(r, 1000));
  document.querySelector('#tabs').replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  // ジョブ単位の再印刷ボタンを全ジョブから撤去
  document.querySelectorAll('.job > button').forEach((b) => { if (b.textContent === '再印刷') b.remove(); });
  const box = [...document.querySelectorAll('.job')].find((j) => j.textContent.includes(D.job_id));
  box.querySelector('button').click();
  await new Promise(r => setTimeout(r, 1000));
  // シート行ごとに再印刷・調整するを置く
  const detail = box.lastElementChild;
  [...detail.children].filter((d) => d.querySelector('a[href*="sheets/"]') && !d.classList.contains('row')).forEach((line) => {
    line.classList.add('sheet-line');
    const tagEl = line.querySelector('.tag');
    const wrap = document.createElement('span');
    D.sheet_buttons.forEach((t) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = t; wrap.append(b); });
    tagEl.after(wrap);
  });
  return { sheetLines: document.querySelectorAll('.sheet-line').length, jobLevelReprint: [...document.querySelectorAll('.job > button')].filter((b) => b.textContent === '再印刷').length, perSheetButtons: document.querySelectorAll('.sheet-line button').length, tabs: document.querySelectorAll('#tabs button').length };
}
