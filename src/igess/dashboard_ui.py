"""Offline presentation for the development Dashboard (no workflow logic)."""

import html


def dashboard_shell(content: str, project: str, mode: str) -> str:
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IGESS Dashboard</title><style>{_CSS}</style></head>
<body data-project="{html.escape(project, quote=True)}">
<a class="skip-link" href="#workspace">Skip to content</a>
<aside class="sidebar">
  <a class="brand" href="#overview"><span class="brand-mark">I</span> IGESS <span class="edition">STUDIO</span></a>
  <div class="project-label">WORKSPACE</div>
  <div class="project-picker"><!-- project-picker --></div>
  <div class="project-name" title="{html.escape(project, quote=True)}">{html.escape(project)}</div>
  <div class="project-mode">{html.escape(mode)}</div>
  <nav aria-label="Workspace navigation">
    <a href="#overview" data-nav="overview"><span aria-hidden="true">▦</span> Overview</a>
    <a href="#runs" data-nav="runs"><span aria-hidden="true">▷</span> Runs &amp; reports</a>
    <a href="#advice" data-nav="advice"><span aria-hidden="true">◇</span> Analyst</a>
  </nav>
  <div class="sidebar-footer"><span class="local-dot"></span> Local workspace<br><small>Game economy simulation</small></div>
</aside>
<div class="workspace">
  <header class="topbar"><span>Workspace <span class="separator">/</span> <strong id="view-label">Overview</strong></span><span class="environment">LOCAL</span></header>
  <main id="workspace" tabindex="-1">
    <div class="page-heading"><div><div class="eyebrow">DEVELOPMENT WORKSPACE</div><h1>IGESS Dashboard</h1>
    <p>Inspect your model. Run scenarios. Understand the results.</p></div><a class="button primary" href="#runs">Run a scenario <span aria-hidden="true">↗</span></a></div>
    <div id="task-slot"></div>
    {content}
  </main>
</div><script>{_SCRIPT}</script></body></html>'''


_CSS = r'''
:root { color-scheme: dark; --bg:#171717; --panel:#1c1c1c; --raised:#232323; --line:#333; --text:#ededed; --muted:#a1a1aa; --green:#3ecf8e; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.6 "Segoe UI",Arial,sans-serif; }
a { color:var(--green); text-decoration:none; } a:hover { text-decoration:underline; }
button,input,select { font:inherit; } button,a,input,select,summary { -webkit-tap-highlight-color:transparent; }
:focus-visible { outline:2px solid var(--green); outline-offset:4px; }
[hidden] { display:none !important; }
.skip-link { position:fixed; top:-80px; left:16px; z-index:10; background:var(--panel); padding:12px; } .skip-link:focus { top:8px; }
.sidebar { position:fixed; inset:0 auto 0 0; width:224px; background:#141414; border-right:1px solid var(--line); padding:24px 16px; display:flex; flex-direction:column; }
.brand { display:flex; align-items:center; gap:9px; color:var(--text); font-size:20px; font-weight:650; letter-spacing:-.5px; }
.brand-mark { display:grid; place-items:center; background:var(--green); color:#10291c; border-radius:7px; width:29px; height:29px; font-weight:800; }
.edition { font-size:9px; color:var(--muted); letter-spacing:1.4px; margin-left:auto; }
.project-label { font-size:10px; letter-spacing:1.7px; color:#858585; margin-top:40px; }
.project-picker select { width:100%; margin-top:4px; } .project-picker label { margin:12px 0 0; }
.project-name { font-weight:600; margin-top:9px; overflow-wrap:anywhere; }
.project-mode { color:var(--muted); font-size:12px; margin:3px 0 27px; }
nav { display:grid; gap:5px; } nav a { color:#adadad; border:1px solid transparent; border-radius:6px; padding:9px 12px; display:flex; align-items:center; gap:12px; }
nav a span { font-size:19px; line-height:1; width:18px; text-align:center; }
nav a:hover { text-decoration:none; color:var(--text); background:#202020; } nav a[aria-current=page] { color:var(--green); background:#1b2a23; border-color:#294135; }
.sidebar-footer { margin-top:auto; color:#b0b0b0; font-size:12px; padding:16px 10px 0; border-top:1px solid var(--line); } .sidebar-footer small { color:#777; padding-left:14px; }
.local-dot { display:inline-block; width:6px; height:6px; background:var(--green); border-radius:50%; margin-right:6px; }
.workspace { margin-left:224px; min-width:0; } .topbar { height:60px; padding:0 36px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; color:var(--muted); font-size:12px; }
.topbar strong { font-weight:400; color:var(--text); } .separator { margin:0 15px; color:#555; } .environment { font:10px Consolas,monospace; letter-spacing:1px; border:1px solid var(--line); border-radius:4px; padding:3px 7px; }
main { max-width:1500px; padding:34px 36px 60px; margin:auto; }
.page-heading { display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:28px; }
.eyebrow { color:var(--muted); font-size:10px; letter-spacing:1.8px; } h1 { font-size:28px; line-height:1.3; font-weight:550; letter-spacing:-.8px; margin:7px 0; }
.page-heading p { margin:0; color:var(--muted); font-size:13px; }
section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:24px; margin-bottom:20px; min-width:0; }
h2 { font-size:16px; font-weight:550; margin:0 0 16px; letter-spacing:-.2px; } h3 { font-size:12px; font-weight:600; color:var(--muted); margin:24px 0 8px; }
p { margin:8px 0 14px; } li { margin:6px 0; overflow-wrap:anywhere; } ul { padding-left:20px; }
code { font:12px/1.6 Consolas,monospace; color:#b7bec6; overflow-wrap:anywhere; }
label { display:block; color:#c5c5c5; font-size:12px; margin-bottom:7px; }
input,select { padding:9px 11px; border:1px solid #414141; border-radius:5px; color:var(--text); background:#191919; min-width:0; max-width:100%; }
button,.button { display:inline-flex; justify-content:center; align-items:center; gap:12px; border:1px solid #454545; border-radius:5px; background:#2b2b2b; color:var(--text); padding:8px 13px; font-size:12px; font-weight:500; cursor:pointer; line-height:1.5; }
button:hover,.button:hover { background:#353535; text-decoration:none; } .primary,form[action$="/formal"] button { background:#27764f; border-color:#329365; color:#f2fff8; } .primary:hover,form[action$="/formal"] button:hover { background:#318b60; }
button:disabled { opacity:.45; cursor:not-allowed; }
.actions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; margin-top:20px; }
.actions form { padding:18px; background:#202020; border:1px solid var(--line); border-radius:6px; display:flex; flex-direction:column; align-items:stretch; justify-content:flex-end; gap:8px; }
.actions form label { margin:0; } .actions form p { color:var(--muted); font-size:12px; }
form > button { margin-top:12px; } form > input:not([type=hidden]),form > select { width:100%; }
.counts { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; margin-top:12px; }
.counts div { padding:15px; border:1px solid var(--line); border-radius:5px; font-size:23px; font-variant-numeric:tabular-nums; }
.run-summary { margin:0 0 24px; } .run-summary div { background:var(--panel); font-size:27px; padding:20px; }
.counts strong { display:block; font-size:11px; color:var(--muted); font-weight:400; margin-bottom:5px; }
.ok,.ready,.runnable,.success { color:#68dba4; } .failed { color:#ff9696; } .incomplete,.running { color:#edc77c; }
.state-badge,.kind { display:inline-block; border:1px solid #444; border-radius:4px; padding:2px 7px; font-size:11px; line-height:1.6; font-weight:500; white-space:nowrap; }
.state-badge.success,.state-badge.ready,.state-badge.runnable { background:#1c3026; border-color:#315b43; } .state-badge.failed { background:#372323; border-color:#633b3b; }
.kind { color:#b3b3bd; } .kind-advice { color:#c5aff4; } .kind-smoke { color:#e2c58e; }
.hint { color:var(--muted); font-size:12px; } details { margin-top:16px; border-top:1px solid var(--line); padding-top:14px; } summary { color:var(--muted); cursor:pointer; font-size:12px; }
.history-toolbar { display:flex; flex-wrap:wrap; align-items:end; gap:12px; margin-bottom:18px; } .search-field { flex:1; min-width:180px; } .history-toolbar input { width:100%; } .history-toolbar label { margin-bottom:5px; }
.table-scroll { overflow:auto; border:1px solid var(--line); border-radius:6px; } table { width:100%; border-collapse:collapse; font-size:12px; }
th { background:#232323; color:var(--muted); font-weight:500; white-space:nowrap; } th,td { padding:13px 16px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
tbody tr:last-child td { border-bottom:0; } tbody tr:hover { background:#222; } td { min-width:90px; max-width:310px; overflow-wrap:anywhere; } td:first-child { min-width:190px; } td:last-child { min-width:140px; }
.empty-state { padding:32px 16px; text-align:center; color:var(--muted); } .empty-state strong { display:block; color:var(--text); font-weight:500; margin-bottom:5px; }
#task-panel { border-left:3px solid #486555; padding:18px 22px; display:grid; grid-template-columns:1fr auto; gap:0 20px; }
#task-panel h2 { font-size:12px; color:var(--muted); margin-bottom:8px; } #task-panel p { font-size:12px; margin:4px 0; overflow-wrap:anywhere; }
#task-panel form { grid-column:2; grid-row:1 / span 5; align-self:center; } #task-panel a { font-size:12px; } #task-panel #task-time { color:var(--muted); } #connection-state:empty { display:none; } #connection-state { color:#edc77c; }
#task-state { font-weight:600; text-transform:capitalize; } #task-message { max-height:160px; overflow:auto; } #task-links { grid-column:1 / -1; }
@media(min-width:1250px) { .overview-grid { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(260px,1fr); gap:20px; align-items:start; } }
@media(max-width:1050px) { .sidebar { width:190px; } .workspace { margin-left:190px; } main { padding:24px; } .topbar { padding:0 24px; } .actions { grid-template-columns:1fr; } }
@media(max-width:700px) { .sidebar { position:static; width:auto; padding:16px; border-right:0; border-bottom:1px solid var(--line); } .brand { max-width:180px; } .project-label,.project-name,.project-mode,.sidebar-footer { display:none; } nav { display:flex; flex-wrap:wrap; margin-top:16px; gap:4px; } nav a { padding:7px 10px; font-size:12px; } .workspace { margin-left:0; } .topbar { height:46px; padding:0 18px; } main { padding:24px 16px; } .page-heading { align-items:flex-start; flex-direction:column; } h1 { font-size:25px; } section { padding:18px; } #task-panel { display:block; } #task-panel form { margin-top:12px; } .history-toolbar > div { flex:1; } .history-toolbar select { width:100%; } }
'''


_SCRIPT = r'''
(() => {
  document.querySelector('#project-picker')?.addEventListener('change', event => {
    location.assign(event.target.value + location.hash);
  });
  const views = ['overview', 'runs', 'advice'];
  function navigate() {
    const view = views.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview';
    document.querySelectorAll('[data-view]').forEach(el => el.hidden = el.dataset.view !== view);
    document.querySelectorAll('[data-nav]').forEach(el => {
      if (el.dataset.nav === view) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    });
    document.querySelector('#view-label').textContent = {overview:'Overview', runs:'Runs & reports', advice:'Analyst'}[view];
  }
  window.addEventListener('hashchange', navigate);
  navigate();
  const key = 'igess-dashboard:' + location.pathname + ':' + document.body.dataset.project;
  let saved = {};
  try { saved = JSON.parse(sessionStorage.getItem(key) || '{}') || {}; } catch (_) {}
  const controls = [...document.querySelectorAll('#history-search, #history-status, #history-kind, #scenario, #advice-scenario')];
  function save() {
    try { sessionStorage.setItem(key, JSON.stringify(Object.fromEntries(controls.map(el => [el.id, el.value])))); } catch (_) {}
  }
  function filter() {
    const search = document.querySelector('#history-search');
    if (!search) return;
    const query = search.value.trim().toLowerCase();
    const status = document.querySelector('#history-status').value;
    const kind = document.querySelector('#history-kind').value;
    const rows = [...document.querySelectorAll('tr[data-run]')];
    let visible = 0;
    rows.forEach(row => {
      row.hidden = !(row.textContent.toLowerCase().includes(query) && (!status || row.dataset.status === status) && (!kind || row.dataset.kind === kind));
      if (!row.hidden) visible++;
    });
    document.querySelector('#history-count').textContent = visible + ' of ' + rows.length + ' runs';
    document.querySelector('#history-no-match').hidden = visible > 0 || rows.length === 0;
  }
  controls.forEach(el => {
    if (typeof saved[el.id] === 'string' && (el.tagName !== 'SELECT' || [...el.options].some(o => o.value === saved[el.id]))) el.value = saved[el.id];
    el.addEventListener('input', () => { save(); filter(); });
    el.addEventListener('change', () => { save(); filter(); });
  });
  document.querySelector('#clear-filters')?.addEventListener('click', () => {
    document.querySelectorAll('#history-search, #history-status, #history-kind').forEach(el => el.value = '');
    save(); filter(); document.querySelector('#history-search').focus();
  });
  filter();
})();
'''
