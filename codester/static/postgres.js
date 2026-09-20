import {$, api, escape as e, ago} from './common.js';

let latest;
let pending;
let actionTrigger;
let actionRunning = false;
let signature = '';
const embedded = Boolean($('#sql-workspace'));
let generation = 0;
const activityPath = () => embedded ? `/api/sql/connections/${encodeURIComponent($('#sql-workspace').dataset.connection || '')}` : '/api/postgres';
const age = value => value == null ? '?' : value < 60 ? `${Math.max(0, Math.floor(value))}s` : `${Math.floor(value / 60)}m ${Math.floor(value % 60)}s`;
function tab(name, focus = false) {
  for (const key of ['queries','locks']) {
    const selected = key === name;
    $(`#pg-tab-${key}`).setAttribute('aria-selected', String(selected));
    $(`#pg-tab-${key}`).tabIndex = selected ? 0 : -1;
    $(`#pg-${key}`).hidden = !selected;
    if (selected && focus) $(`#pg-tab-${key}`).focus();
  }
  if (!embedded) history.replaceState(null, '', `#${name}`);
}
for (const name of ['queries','locks']) {
  $(`#pg-tab-${name}`).addEventListener('click', () => tab(name));
  $(`#pg-tab-${name}`).addEventListener('keydown', event => {
    if (['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) { event.preventDefault(); tab(event.key === 'Home' ? 'queries' : event.key === 'End' ? 'locks' : name === 'queries' ? 'locks' : 'queries', true); }
  });
}
function session(row, context) {
  const canAct = latest.state.status === 'connected' && !latest.demo && Boolean(row.token) && !actionRunning;
  const key = `${context}-${row.pid}`;
  const queryLabel = row.state === 'active' ? 'Current query' : 'Last query';
  return `<article class="pg-session"><div class="pg-session-header"><div class="pg-session-meta"><strong>PID ${row.pid}</strong>${e(row.username || 'Unknown user')} / ${e(row.application_name || 'No app name')}<br>${e(row.state || 'Hidden state')} / query ${age(row.query_seconds)} / transaction ${age(row.transaction_seconds)}${row.wait_event ? ` / ${e(row.wait_event)}` : ''}</div><div class="pg-session-actions"><button class="quiet-button" data-pid="${row.pid}" data-action="cancel" data-key="${key}-cancel" ${!canAct || row.state !== 'active' ? 'disabled' : ''}>Cancel query</button><button class="quiet-button pg-terminate" data-pid="${row.pid}" data-action="terminate" data-key="${key}-terminate" ${!canAct ? 'disabled' : ''}>End session</button></div></div><details data-query="${key}"><summary>${queryLabel}: ${e((row.query || 'Not visible to this database role').slice(0, 180))}</summary><pre>${e(row.query || 'Query text is unavailable.')}</pre></details></article>`;
}
function render() {
  if (!latest) return;
  const state = latest.state;
  const data = state.data;
  $('#pg-freshness').textContent = `${state.status === 'demo' ? 'Demo' : state.status === 'connected' ? 'Live' : state.status} / ${state.last_success ? ago(state.last_success) : 'No reading yet'}`;
  const notices = [];
  if (['error','stale','disabled'].includes(state.status)) notices.push(state.message);
  if (data?.hidden_sessions) notices.push(`${data.hidden_sessions} sessions have limited visibility. pg_read_all_stats allows the role to see other users' activity.`);
  if (data && !data.tracking) notices.push('track_activities is disabled; query activity is incomplete.');
  if (latest.demo) notices.push('Sample data. Session controls are disabled.');
  $('#pg-notice').textContent = notices.join(' '); $('#pg-notice').hidden = !notices.length;
  $('#pg-database').textContent = data ? `${data.database} / connected as ${data.username}` : 'Configure a connection in Settings';
  $('#pg-counts').innerHTML = data ? [[data.active,data.hidden_sessions ? 'visible active' : 'active'],[data.waiting,'waiting'],[data.idle_transactions,'idle transactions'],[data.sessions,'sessions'],[data.held_locks,'held locks']].map(([value,label]) => `<div class="${label === 'waiting' && value ? 'waiting' : ''}"><strong>${value}</strong><span>${label}</span></div>`).join('') : '';
  const next = JSON.stringify([state.status, latest.demo, data, actionRunning]);
  if (next === signature) return;
  signature = next;
  const expanded = new Set([...document.querySelectorAll('[data-query][open]')].map(node => node.dataset.query));
  const focused = document.activeElement?.dataset.key;
  $('#pg-query-note').textContent = data ? `Oldest first. Showing up to ${data.query_limit} active or idle-in-transaction sessions. Query text is capped at 4,000 characters and PostgreSQL may truncate it further.` : '';
  $('#pg-query-list').innerHTML = data?.queries.length ? data.queries.map(row => session(row, 'query')).join('') : '<p class="muted">No visible active queries or idle transactions.</p>';
  $('#pg-lock-note').textContent = data ? `${data.waiting} sessions waiting; ${data.held_locks} held locks (usually normal). Blocker details cover up to ${data.wait_limit} waiting sessions. End the blocking session to release its transaction locks.` : '';
  const sessions = new Map((data?.lock_sessions || []).map(row => [row.pid, row]));
  $('#pg-lock-list').innerHTML = data?.blocking.length ? data.blocking.map((edge, index) => {
    const waiting = sessions.get(edge.waiting_pid); const blocking = sessions.get(edge.blocking_pid);
    const locks = (data.locks || []).filter(lock => lock.pid === edge.waiting_pid).map(lock => `${lock.mode} / ${lock.relation || lock.locktype}`).join(', ');
    return `<section class="pg-lock-edge"><h3>PID ${edge.waiting_pid} waits for ${edge.blocking_pid ? `PID ${edge.blocking_pid}` : 'a prepared transaction'}</h3><p>${e(locks)}</p>${waiting ? session(waiting, `wait-${index}`) : '<p>Waiting session ended or is unavailable.</p>'}<p>Blocking session</p>${blocking ? session(blocking, `block-${index}`) : `<p>${edge.blocking_pid ? 'Blocker ended or is unavailable.' : 'Prepared transactions have no live PID. Resolve this in your database administration tool.'}</p>`}</section>`;
  }).join('') : '<p class="muted">No blocking sessions observed.</p>';
  for (const details of document.querySelectorAll('[data-query]')) details.open = expanded.has(details.dataset.query);
  if (focused) [...document.querySelectorAll('[data-key]')].find(node => node.dataset.key === focused)?.focus({preventScroll:true});
}
function closeConfirmation() {
  pending = null; $('#pg-confirmation').hidden = true;
  if (actionTrigger) [...document.querySelectorAll('[data-key]')].find(node => node.dataset.key === actionTrigger)?.focus({preventScroll:true});
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-action][data-pid]');
  if (!button || button.disabled) return;
  const row = [...(latest.state.data?.queries || []), ...(latest.state.data?.lock_sessions || [])].find(row => row.pid === Number(button.dataset.pid));
  if (!row?.token) return;
  pending = {token:row.token, action:button.dataset.action}; actionTrigger = button.dataset.key;
  $('#pg-confirm-title').textContent = `${pending.action === 'cancel' ? 'Cancel query' : 'End session'}: PID ${row.pid} / ${row.username}`;
  $('#pg-confirm-description').textContent = pending.action === 'cancel' ? 'Requests cancellation of the current query. An open transaction may still hold locks.' : 'Disconnects this session and rolls back its open transaction. Its application may reconnect.';
  $('#pg-confirm-query').textContent = row.query || 'Query unavailable';
  $('#pg-confirm-action').textContent = pending.action === 'cancel' ? 'Cancel query' : 'End session';
  $('#pg-confirmation').hidden = false; $('#pg-confirm-title').focus();
});
$('#pg-cancel-action').addEventListener('click', closeConfirmation);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !actionRunning) closeConfirmation(); });
$('#pg-confirm-action').addEventListener('click', async () => {
  if (!pending || actionRunning) return;
  actionRunning = true; $('#pg-confirm-action').disabled = true; $('#pg-cancel-action').disabled = true; render();
  const result = $('#pg-action-result'); result.hidden = false; result.classList.remove('error'); result.textContent = 'Sending request';
  try { const response = await api(`${activityPath()}/${pending.action}`, {method:'POST',body:JSON.stringify({token:pending.token}),timeout:15000}); result.textContent = response.message; closeConfirmation(); }
  catch (error) { result.textContent = error.message; result.classList.add('error'); }
  finally { actionRunning = false; $('#pg-confirm-action').disabled = false; $('#pg-cancel-action').disabled = false; await refresh(); if ($('#pg-confirmation').hidden && actionTrigger) [...document.querySelectorAll('[data-key]')].find(node => node.dataset.key === actionTrigger)?.focus({preventScroll:true}); }
});
async function refresh() {
  if (embedded && (!$('#sql-workspace').dataset.connection || $('#sql-workspace').hidden || $('#sql-activity-view').hidden)) return;
  const version = generation;
  try {
    const response = await api(embedded ? `${activityPath()}/activity` : '/api/postgres', {timeout:8000});
    if (version !== generation) return;
    latest = response; render();
  } catch {
    if (version !== generation) return;
    if (latest) { latest.state.status = 'stale'; latest.state.message = 'Could not refresh activity. Session controls paused.'; render(); }
    else { $('#pg-notice').textContent = 'Could not read PostgreSQL status. Check the connection and SSH tunnel.'; $('#pg-notice').hidden = false; }
  }
}
if (embedded) {
  document.addEventListener('sqlconnectionchange', () => {
    generation += 1; latest = null; signature = ''; closeConfirmation();
    for (const id of ['pg-counts','pg-query-list','pg-lock-list','pg-database','pg-query-note','pg-lock-note']) $(`#${id}`).textContent = '';
    $('#pg-freshness').textContent = 'No reading yet';
    $('#pg-notice').hidden = true; $('#pg-action-result').hidden = true;
    refresh();
  });
  document.addEventListener('sqlactivitychange', refresh);
  document.addEventListener('workspacechange', refresh);
}
tab(location.hash === '#locks' ? 'locks' : 'queries');
await refresh();
async function poll() { if (!document.hidden && !actionRunning) await refresh(); setTimeout(poll, 3000); }
setTimeout(poll, 3000);
