import {$, api, escape as e, epoch} from './common.js';
import {activeWorkspace} from './workspaces.js';

let mode = 'recent';
let paused = false;
let busy = false;
let revision = 0;
let timer;
let lastSuccess = null;
const target = $('#logs-table');
const status = $('#logs-status');
function visible() {
  return activeWorkspace() === 'signoz' && !document.hidden && !$('#overview').hidden && !$('#overview').classList.contains('detail-open');
}
function time(value) {
  const date = new Date(epoch(value) * 1000);
  return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {hour12:false}) : '—';
}
function render(data) {
  const open = new Set([...target.querySelectorAll('details[open]')].map(row => row.dataset.logId));
  const focus = document.activeElement?.closest('[data-log-id]')?.dataset.logId;
  const scroll = target.scrollTop;
  if (!data.rows.length) {
    target.innerHTML = `<p class="log-empty">${e(data.status === 'connected' ? `No ${mode === 'errors' ? 'error ' : ''}logs in the last 15 minutes.` : data.status === 'demo' ? 'No demo logs.' : 'Logs unavailable.')}</p>`;
    return;
  }
  const markup = `<table><thead><tr><th>Time</th><th>Level</th><th>App</th><th>user.id</th><th>Log</th></tr></thead><tbody>${data.rows.map(row => `<tr>
    <td>${e(time(row.timestamp))}</td><td class="log-level ${['ERROR','FATAL','CRITICAL'].includes(row.severity.toUpperCase()) ? 'is-error' : ''}">${e(row.severity || '—')}</td>
    <td>${e(row.app || '—')}</td><td>${e(row.user_id || '—')}</td>
    <td><details data-log-id="${e(row.id)}" ${open.has(row.id) ? 'open' : ''}><summary>${e(row.body.split('\n')[0] || '(empty message)')}</summary><pre>${e(row.body)}</pre>${row.truncated ? '<small>Message truncated at 4,000 characters.</small>' : ''}</details></td>
  </tr>`).join('')}</tbody></table>`;
  if (target.innerHTML !== markup) target.innerHTML = markup;
  target.scrollTop = scroll;
  if (focus) [...target.querySelectorAll('details')].find(row => row.dataset.logId === focus)?.querySelector('summary').focus({preventScroll:true});
}
async function refresh() {
  clearTimeout(timer);
  if (busy || paused || !visible()) { timer = setTimeout(refresh, 5000); return; }
  busy = true;
  const requestRevision = revision;
  try {
    const data = await api(`/api/signoz/logs?mode=${mode}`, {timeout:20000});
    if (paused || requestRevision !== revision || !visible()) return;
    render(data);
    lastSuccess = data.last_success;
    status.textContent = data.status === 'connected' ? `${data.rows.length} logs · Updated ${time(lastSuccess)}`
      : `${data.message}${lastSuccess && data.status !== 'demo' ? ` · Last read ${time(lastSuccess)}` : ''}`;
    status.classList.toggle('is-error', ['error','stale'].includes(data.status));
  } catch (error) {
    if (requestRevision === revision && !paused) {
      // Do not retain logs when the current connection/credential state cannot be checked.
      target.replaceChildren();
      status.textContent = `Logs unavailable. ${error.message}`;
      status.classList.add('is-error');
    }
  } finally { busy = false; timer = setTimeout(refresh, 5000); }
}
for (const button of document.querySelectorAll('[data-log-mode]')) button.addEventListener('click', () => {
  if (mode === button.dataset.logMode) return;
  mode = button.dataset.logMode;
  revision += 1;
  for (const option of document.querySelectorAll('[data-log-mode]')) option.setAttribute('aria-pressed', String(option === button));
  target.replaceChildren();
  lastSuccess = null;
  status.textContent = paused ? 'Paused. Resume to load this filter.' : 'Loading logs…';
  refresh();
});
$('#logs-pause').addEventListener('click', () => {
  paused = !paused;
  revision += 1;
  $('#logs-pause').textContent = paused ? 'Resume' : 'Pause';
  $('#logs-pause').setAttribute('aria-pressed', String(paused));
  status.textContent = paused ? `Paused${lastSuccess ? ` · Last read ${time(lastSuccess)}` : ''}` : 'Refreshing logs…';
  refresh();
});
document.addEventListener('workspacechange', () => { revision += 1; refresh(); });
document.addEventListener('visibilitychange', () => { revision += 1; refresh(); });
refresh();
