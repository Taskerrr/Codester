import {$, api, escape as e, epoch} from './common.js';
import {activeWorkspace} from './workspaces.js';

const form = $('#logs-filters');
const target = $('#logs-table');
const status = $('#logs-status');
const detail = $('#logs-detail');
const defaults = {text:'', app:'', user_id:'', level:'', seconds:'900', trace_id:''};
let filters = {...defaults};
let mode = 'recent';
let paused = false;
let busy = false;
let queued = false;
let revision = 0;
let timer;
let offset = 0;
let end = 0;
let snapshot = null;
let selected = null;

function visible() {
  return activeWorkspace() === 'signoz' && !document.hidden && !$('#overview').hidden && !$('#overview').classList.contains('detail-open');
}
function time(value, full = false) {
  const stamp = epoch(value);
  if (stamp == null) return 'Unavailable';
  const date = new Date(stamp * 1000);
  if (!Number.isFinite(date.getTime())) return 'Unavailable';
  return full ? date.toLocaleString([], {hour12:false}) : date.toLocaleTimeString([], {hour12:false});
}
function safeURL(value) {
  if (!value) return '';
  try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) ? url.href : ''; }
  catch { return ''; }
}
function setPaused(value) {
  paused = value;
  $('#logs-pause').textContent = paused ? 'Resume live' : 'Pause';
  $('#logs-pause').setAttribute('aria-pressed', String(paused));
}
function updateStatus() {
  if (!snapshot) return;
  const data = snapshot;
  const source = data.status === 'demo' ? 'Demo · ' : '';
  status.textContent = ['connected','demo'].includes(data.status)
    ? `${source}${paused ? 'Paused' : 'Live'} · ${data.rows.length} logs · ${time(data.last_success)}`
    : `${data.message}${data.last_success ? ` · Last read ${time(data.last_success)}` : ''}`;
  status.classList.toggle('is-error', ['error','stale'].includes(data.status));
}
function pages() {
  const ready = snapshot && ['connected','demo'].includes(snapshot.status) && !busy;
  $('#logs-newest').disabled = busy || (!offset && !end);
  $('#logs-newer').disabled = !ready || offset === 0;
  $('#logs-older').disabled = !ready || !snapshot.page_full || offset >= 900;
  $('#logs-page').textContent = `Page ${offset / 100 + 1}`;
}
function closeDetail(focus = false) {
  const id = selected?.id;
  selected = null;
  detail.hidden = true;
  $('#logs-detail-content').replaceChildren();
  $('#logs-copy-status').textContent = '';
  for (const row of target.querySelectorAll('tr.is-selected')) row.classList.remove('is-selected');
  for (const button of target.querySelectorAll('[data-log-id]')) {
    button.setAttribute('aria-expanded', 'false');
    if (focus && button.dataset.logId === id) button.focus({preventScroll:true});
  }
}
function render(data) {
  const focus = target.contains(document.activeElement) ? document.activeElement?.dataset.focusKey : null;
  const scroll = target.scrollTop;
  const source = safeURL(data.source_url);
  $('#logs-source').hidden = !source;
  if (source) $('#logs-source').href = source;
  else $('#logs-source').removeAttribute('href');
  if (!data.rows.length) {
    target.innerHTML = `<p class="log-empty">${e(['connected','demo'].includes(data.status) ? 'No logs match this search. Try a longer time range or clear a filter.' : data.status === 'disabled' ? data.message : 'Logs unavailable. Check the connection and try again.')}</p>`;
  } else {
    const markup = `<table><thead><tr><th>Time</th><th>Level</th><th>App</th><th>User ID</th><th>Message</th></tr></thead><tbody>${data.rows.map(row => `<tr class="${selected?.id === row.id ? 'is-selected' : ''}">
      <td title="${e(time(row.timestamp, true))}">${e(time(row.timestamp))}</td>
      <td class="log-level ${['ERROR','FATAL','CRITICAL'].includes(row.severity.toUpperCase()) ? 'is-error' : ''}">${e(row.severity || '—')}</td>
      <td>${row.app ? `<button type="button" data-filter="app" data-value="${e(row.app)}" data-focus-key="app-${e(row.id)}" title="Filter app: ${e(row.app)}">${e(row.app)}</button>` : '—'}</td>
      <td>${row.user_id ? `<button type="button" data-filter="user_id" data-value="${e(row.user_id)}" data-focus-key="user-${e(row.id)}" title="Filter user: ${e(row.user_id)}">${e(row.user_id)}</button>` : '—'}</td>
      <td><button type="button" class="log-message" data-log-id="${e(row.id)}" data-focus-key="message-${e(row.id)}" aria-controls="logs-detail" aria-expanded="${selected?.id === row.id}">${e(row.body.split('\n')[0] || '(empty message)')}</button></td>
    </tr>`).join('')}</tbody></table>`;
    if (target.innerHTML !== markup) target.innerHTML = markup;
  }
  target.scrollTop = scroll;
  if (focus) [...target.querySelectorAll('[data-focus-key]')].find(el => el.dataset.focusKey === focus)?.focus({preventScroll:true});
  $('#logs-apps').innerHTML = [...new Set(data.rows.map(row => row.app).filter(Boolean))].sort().map(app => `<option value="${e(app)}"></option>`).join('');
  $('#logs-range').textContent = `${time(data.start_ms, true)} → ${time(data.end_ms, true)} · ${offset >= 900 && data.page_full ? '1,000-log limit; narrow your search.' : '100 per page. Live checks every 5s; busy periods can skip entries.'}`;
}
function showDetail(row) {
  selected = row;
  setPaused(true);
  revision += 1;
  detail.hidden = false;
  const traceURL = safeURL(row.trace_url);
  const metadata = [['Time',time(row.timestamp, true)],['Level',row.severity],['App',row.app],['User ID',row.user_id],['Trace ID',row.trace_id],['Span ID',row.span_id]];
  $('#logs-detail-content').innerHTML = `
    <pre>${e(row.body || '(empty message)')}</pre>
    ${row.truncated ? '<small>Message preview truncated at 4,000 characters. Open SigNoz for the full record.</small>' : ''}
    <dl class="log-metadata">${metadata.map(([label,value]) => `<dt>${e(label)}</dt><dd>${e(value || 'Not supplied')}</dd>`).join('')}</dl>
    <div class="log-detail-links">
      ${row.app ? `<button type="button" data-filter="app" data-value="${e(row.app)}">Filter app</button>` : ''}
      ${row.user_id ? `<button type="button" data-filter="user_id" data-value="${e(row.user_id)}">Filter user</button>` : ''}
      ${row.trace_id ? `<button type="button" data-filter="trace_id" data-value="${e(row.trace_id)}">Logs for this trace</button>` : ''}
      ${traceURL ? `<a href="${e(traceURL)}" target="_blank" rel="noopener noreferrer">Open trace ↗</a>` : ''}
    </div>
    <details open><summary>Attributes · ${Object.keys(row.attributes || {}).length}</summary>
      <dl class="log-attributes">${Object.entries(row.attributes || {}).map(([key,value]) => `<dt>${e(key)}</dt><dd>${e(value)}</dd>`).join('')}</dl>
      ${row.attributes_truncated ? '<small>Attribute preview truncated. Open SigNoz for all attributes.</small>' : ''}
    </details>`;
  $('#logs-copy-status').textContent = '';
  detail.scrollTop = 0;
  render(snapshot);
  updateStatus();
  $('#logs-detail-title').focus({preventScroll:true});
}
export function openHomeLog(data, identifier) {
  const row = data?.rows?.find(item => item.id === identifier);
  if (!row) return;
  filters = {...defaults};
  mode = data.mode === 'errors' ? 'errors' : 'recent';
  offset = 0;
  end = 0;
  revision += 1;
  snapshot = data;
  syncMode();
  form.reset();
  $('#logs-filter-state').textContent = '';
  closeDetail();
  showDetail(row);
}
async function refresh(manual = false) {
  clearTimeout(timer);
  if (busy) { queued ||= manual; return; }
  if (!visible() || (paused && !manual)) { timer = setTimeout(refresh, 5000); return; }
  busy = true;
  pages();
  const requestRevision = revision;
  const params = new URLSearchParams({...filters, mode, offset:String(offset), end_ms:String(end)});
  try {
    const data = await api(`/api/signoz/logs?${params}`, {timeout:20000});
    if (requestRevision !== revision || !visible()) return;
    snapshot = data;
    render(data);
    updateStatus();
  } catch (error) {
    if (requestRevision === revision && visible()) {
      snapshot = null;
      target.replaceChildren();
      closeDetail();
      $('#logs-source').hidden = true;
      status.textContent = `Logs unavailable. ${error.message}`;
      status.classList.add('is-error');
    }
  } finally {
    busy = false;
    pages();
    if (queued) { queued = false; refresh(true); }
    else timer = setTimeout(refresh, 5000);
  }
}
function apply() {
  if (!form.reportValidity()) return;
  filters = Object.fromEntries(new FormData(form));
  for (const key of Object.keys(filters)) filters[key] = String(filters[key]).trim();
  offset = 0;
  end = 0;
  revision += 1;
  snapshot = null;
  closeDetail();
  target.innerHTML = '<p class="log-empty">Searching logs…</p>';
  status.textContent = 'Searching SigNoz…';
  status.classList.remove('is-error');
  const count = Object.entries(filters).filter(([key,value]) => key !== 'seconds' && value).length;
  $('#logs-filter-state').textContent = count ? `${count} active filter${count === 1 ? '' : 's'}` : '';
  refresh(true);
}
form.addEventListener('submit', event => { event.preventDefault(); apply(); });
form.addEventListener('input', () => { $('#logs-filter-state').textContent = 'Search to apply changes'; });
form.addEventListener('keydown', event => {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); apply(); }
});
$('#logs-clear').addEventListener('click', () => { form.reset(); mode = 'recent'; syncMode(); apply(); });
function syncMode() {
  for (const button of document.querySelectorAll('[data-log-mode]')) button.setAttribute('aria-pressed', String(button.dataset.logMode === mode));
}
for (const button of document.querySelectorAll('[data-log-mode]')) button.addEventListener('click', () => {
  mode = button.dataset.logMode;
  form.elements.namedItem('level').value = '';
  syncMode(); apply();
});
$('#signoz-log-feed').addEventListener('click', event => {
  const filter = event.target.closest('[data-filter]');
  if (filter) {
    if (filter.dataset.filter === 'trace_id') {
      form.reset(); mode = 'recent'; syncMode();
      form.elements.namedItem('seconds').value = filters.seconds;
    }
    form.elements.namedItem(filter.dataset.filter).value = filter.dataset.value;
    apply();
    return;
  }
  const button = event.target.closest('[data-log-id]');
  if (button) {
    const row = snapshot?.rows.find(row => row.id === button.dataset.logId);
    if (row) showDetail(row);
  }
});
$('#logs-close').addEventListener('click', () => closeDetail(true));
detail.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeDetail(true); } });
$('#logs-pause').addEventListener('click', () => {
  revision += 1;
  setPaused(!paused);
  if (!paused) {
    offset = 0; end = 0; closeDetail();
    snapshot = null; target.replaceChildren();
    status.textContent = 'Refreshing logs…';
    refresh(true);
  } else updateStatus();
});
$('#logs-charts').addEventListener('click', () => {
  const shown = $('[data-app-panel="signoz"]').classList.toggle('show-log-charts');
  $('#logs-charts').setAttribute('aria-pressed', String(shown));
});
function page(direction) {
  if (!snapshot) return;
  end = end || snapshot.end_ms;
  offset += direction * 100;
  setPaused(true);
  revision += 1;
  closeDetail();
  snapshot = null;
  target.innerHTML = '<p class="log-empty">Loading page…</p>';
  status.textContent = 'Loading logs…';
  refresh(true);
}
$('#logs-older').addEventListener('click', () => page(1));
$('#logs-newer').addEventListener('click', () => page(-1));
$('#logs-newest').addEventListener('click', () => { setPaused(false); apply(); });
function context(row) {
  return [
    'SigNoz debugging context', snapshot?.status === 'demo' ? 'Source: DEMO' : `Source: ${snapshot?.source_url || 'SigNoz'}`,
    `Log ID: ${row.id}`, `Timestamp: ${row.timestamp} (${time(row.timestamp, true)})`,
    `App: ${row.app || 'Not supplied'}`, `User ID: ${row.user_id || 'Not supplied'}`, `Severity: ${row.severity || 'Not supplied'}`,
    `Trace ID: ${row.trace_id || 'Not supplied'}`, `Span ID: ${row.span_id || 'Not supplied'}`,
    row.trace_url ? `Trace: ${row.trace_url}` : '', `Last read: ${time(snapshot?.last_success, true)}`,
    `Filters: ${JSON.stringify({...filters, mode})}`, '', 'Message:', row.body,
    row.truncated ? '[Message preview truncated]' : '', '', 'Attributes:', JSON.stringify(row.attributes || {}, null, 2),
    row.attributes_truncated ? '[Attribute preview truncated]' : '',
  ].filter(line => line !== '').join('\n');
}
async function copy(messageOnly) {
  if (!selected) return;
  const row = selected;
  try {
    await navigator.clipboard.writeText(messageOnly ? row.body : context(row));
    if (selected === row) $('#logs-copy-status').textContent = messageOnly ? 'Message copied.' : 'Debug context copied.';
  } catch {
    if (selected === row) $('#logs-copy-status').textContent = 'Clipboard unavailable. Select and copy the text above.';
  }
}
$('#logs-copy').addEventListener('click', () => copy(false));
$('#logs-copy-message').addEventListener('click', () => copy(true));
document.addEventListener('workspacechange', () => { revision += 1; refresh(); });
document.addEventListener('visibilitychange', () => { revision += 1; refresh(); });
refresh();
