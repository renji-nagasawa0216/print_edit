async () => {
  const D = {"tabs":["取り込み","名刺マスタ","PDF 作成","履歴","印刷待ち","設定作成","全体設定"],"active":"履歴","ingest_button":"取込&作成","dialog":{"title":"取込&作成","desc":"監視フォルダの新しい画像を取り込み、選んだ既定値で PDF を作成します。取り込んだ名刺は登録待ちに入ります（マスタには自動で登録しません）。","presets":["既定","名刺10面・名刺間トンボ"],"selected":"既定","target":"未取り込みの画像 3 件","ok":"実行","cancel":"キャンセル"}};
  if (!document.getElementById('mock-style')) {
    const st = document.createElement('style'); st.id = 'mock-style';
    st.textContent = 'header{flex-wrap:wrap}nav{display:flex;flex-wrap:wrap;gap:4px}#ingest-btn{margin-left:auto;padding:6px 12px;font-weight:bold}';
    document.head.append(st);
  }
  show('history');
  await new Promise(r => setTimeout(r, 1000));
  const nav = document.querySelector('#tabs');
  nav.replaceChildren(...D.tabs.map((t) => { const b = document.createElement('button'); b.textContent = t; if (t === D.active) b.className = 'active'; return b; }));
  document.querySelector('#ingest-btn').textContent = D.ingest_button;
  document.querySelectorAll('.job > button').forEach((b) => { if (b.textContent === '再印刷') b.remove(); });
  window.__mockDialog = () => {
    const d = D.dialog;
    const ov = document.createElement('div'); ov.id = 'mock-dialog';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.35);display:flex;align-items:flex-start;justify-content:center;padding-top:80px;z-index:9';
    ov.innerHTML = `<div style="background:#fff;border:1px solid #888;padding:16px;width:min(420px,86vw)"><h3 style="margin:0 0 8px">${d.title}</h3><p style="margin:0 0 12px">${d.desc}</p><div class="hint">対象: ${d.target}</div><label>使う既定値 <select>${d.presets.map((p) => `<option${p === d.selected ? ' selected' : ''}>${p}</option>`).join('')}</select></label><div style="text-align:right;margin-top:12px"><button type="button">${d.cancel}</button> <button type="button" style="font-weight:bold">${d.ok}</button></div></div>`;
    document.body.append(ov);
  };
  return [nav.children.length, document.querySelector('#ingest-btn').textContent, document.querySelectorAll('.job').length, [...document.querySelectorAll('.job > button')].filter((b) => b.textContent === '再印刷').length];
}
