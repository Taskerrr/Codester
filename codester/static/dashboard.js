import {$, api, escape as e, duration, ago} from './common.js';

let latest;
let detailTrigger;
let detailController;

const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const clamp = value => Math.min(100, Math.max(0, number(value)));
const empty = text => `<p class="deck-empty">${e(text)}</p>`;
const spinner = label => `<span class="loading-ring" role="img" aria-label="${e(label)}"></span>`;
const sectionHeading = (title, aside = '') => `<div class="mini-heading"><h3>${e(title)}</h3><span>${e(aside)}</span></div>`;

function ring({value, label, detail = '', progress = 0, live = false}) {
  const safeProgress = live ? 92 : clamp(progress);
  const display = value === null || value === undefined ? '—' : e(value);
  return `<div class="metric-ring ${live ? 'reading-ring' : ''}">
    <div class="ring-visual">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle class="ring-track" cx="60" cy="60" r="51" pathLength="100"/>
        <circle class="ring-progress" cx="60" cy="60" r="51" pathLength="100" stroke-dasharray="${safeProgress} 100"/>
      </svg>
      <div class="ring-value"><strong>${display}</strong><span>${e(label)}</span></div>
    </div>
    <small>${e(detail)}</small>
  </div>`;
}

function errors(name, rows, limit = 3) {
  if (!rows.length) return '<div class="all-clear"><span>✓</span> Clear</div>';
  return `<div class="deck-errors">${rows.slice(0, limit).map(row => `<button class="deck-error" type="button" data-service="${name}" data-id="${e(row.id)}">
    <span class="failure-mark" aria-label="Failed">!</span>
    <span class="error-title">${e(row.title)}</span>
    <time>${ago(row.timestamp)}</time>
  </button>`).join('')}</div>`;
}

function codex(data) {
  const windows = data.windows.slice(0, 2).map(window => {
    const used = Number.isFinite(window.used) ? clamp(window.used) : null;
    const label = window.minutes === 300 ? '5-HOUR' : window.minutes === 10080 ? 'WEEKLY' : 'USAGE';
    const reset = window.resets ? `resets ${duration(window.resets - Date.now() / 1000)}` : 'reset unavailable';
    return ring({value: used === null ? null : `${Math.round(used)}%`, label, detail: reset, progress: used});
  }).join('');
  const tasks = data.tasks.slice(0, 3).map(task => `<div class="recent-row">
    <div><strong title="${e(task.title)}">${e(task.title)}</strong><small>${e(task.project)}</small></div>
    <time>${ago(task.timestamp)}</time>
  </div>`).join('');
  return `<div class="hero-rings codex-rings">${windows || empty('Usage unavailable')}</div>
    ${sectionHeading('Recent activity')}
    <div class="recent-list">${tasks || empty('No recent activity')}</div>`;
}

function dagster(data) {
  const running = number(data.running);
  const queued = number(data.queued);
  const total = running + queued;
  const jobs = data.jobs.slice(0, 3).map(job => `<div class="compact-row">
    ${job.status === 'STARTED' ? spinner('Running') : '<span class="state-mark">!</span>'}
    <strong title="${e(job.title)}">${e(job.title)}</strong>
    <time>${duration(job.duration)}</time>
  </div>`).join('');
  return `<div class="dagster-hero hero-rings">
        ${ring({value: running, label: 'RUNNING', progress: total ? running / total * 100 : 0})}
        ${ring({value: queued, label: 'QUEUED', progress: total ? queued / total * 100 : 0, detail: queued && data.oldest != null ? `oldest ${duration(data.oldest)}` : ''})}
    </div>
    <div class="split-lists">
      <section>${sectionHeading('Recent jobs')}<div class="compact-list">${jobs || empty('Idle')}</div></section>
      <section>${sectionHeading('Errors')}${errors('dagster', data.errors)}</section>
    </div>`;
}

function selectPanel(panels, metric, fallbackIndex) {
  return panels.find(panel => panel.metric === metric) || panels[fallbackIndex] || null;
}

function reading(panel, fallbackLabel) {
  if (!panel) return ring({value: null, label: '', detail: fallbackLabel, live: true});
  const value = panel.value == null ? null : Number(panel.value).toLocaleString(undefined, {maximumFractionDigits: 1});
  return ring({value, label: panel.unit, detail: panel.label, live: true});
}

function signoz(data) {
  const panels = data.panels || [];
  const requestRate = selectPanel(panels, 'request_rate', 0);
  const latency = selectPanel(panels, 'p95', requestRate === panels[0] ? 1 : 0);
  const apps = (data.top_apps || []).slice(0, 3);
  const peak = Math.max(...apps.map(app => number(app.rate)), 1);
  const appRows = apps.map(app => `<div class="app-row">
    <div><strong title="${e(app.service)}">${e(app.service)}</strong><svg class="app-bar" viewBox="0 0 100 2" preserveAspectRatio="none" aria-hidden="true"><rect width="${number(app.rate) / peak * 100}" height="2"/></svg></div>
    <b>${number(app.rate).toLocaleString(undefined, {maximumFractionDigits: 1})} <small>req/s</small></b>
  </div>`).join('');
  return `<div class="hero-rings signoz-rings">${reading(requestRate, 'Request rate')}${reading(latency, 'p95 latency')}</div>
    <div class="split-lists signoz-lists">
      <section>${sectionHeading('Top apps', '5 min')}<div class="app-list">${appRows || empty(data.top_apps_message || 'No requests')}</div></section>
      <section>${sectionHeading('Errors')}${errors('signoz', data.errors)}</section>
    </div>`;
}

const renderers = {codex, dagster, signoz};

function render(snapshot) {
  for (const [name, state] of Object.entries(snapshot.services)) {
    const status = $(`#${name}-status`);
    const channel = status.closest('.channel');
    channel.dataset.state = state.status;
    const issue = ['error', 'stale'].includes(state.status);
    status.dataset.state = state.status;
    status.textContent = issue ? (state.status === 'stale' ? 'Stale' : 'Offline') : '';
    const freshness = state.last_success ? `Updated ${ago(state.last_success)}` : 'No reading yet';
    status.title = `${state.status} · ${freshness}`;
    status.setAttribute('aria-label', `${name}: ${state.status}. ${freshness}`);
    const message = $(`#${name}-message`);
    message.innerHTML = issue ? `<details><summary>${state.last_success ? `Last read ${ago(state.last_success)}` : 'Connection failed'}</summary><p>${e(state.message)}</p></details>` : '';
    const target = $(`#${name}-content`);
    const active = document.activeElement;
    const focusedId = target.contains(active) ? active.dataset.id : null;
    const scrollTop = target.scrollTop;
    target.innerHTML = state.data
      ? renderers[name](state.data)
      : state.status === 'loading'
        ? spinner('Loading')
        : empty(state.status === 'disabled' ? 'Not connected' : 'No data') + '<a class="connect-link" href="/settings">Connect ↗</a>';
    target.scrollTop = scrollTop;
    if (focusedId) Array.from(target.querySelectorAll('[data-id]')).find(element => element.dataset.id === focusedId)?.focus({preventScroll: true});
  }
}

async function refresh() {
  try {
    latest = await api('/api/dashboard', {timeout: 8000});
    $('#connection-warning').hidden = true;
    if ($('#detail').hidden) render(latest);
  } catch {
    $('#connection-warning').textContent = 'Disconnected · readings paused';
    $('#connection-warning').hidden = false;
  } finally {
    setTimeout(refresh, document.hidden ? 15000 : 5000);
  }
}

async function openDetail(button) {
  detailTrigger = {service: button.dataset.service, id: button.dataset.id};
  $('#overview').hidden = true;
  $('#detail').hidden = false;
  $('#detail-title').textContent = 'Loading…';
  $('#detail-source').textContent = button.dataset.service;
  $('#detail-title').focus();
  $('#detail-text').textContent = '';
  $('#detail-note').textContent = '';
  $('#detail-link').hidden = true;
  const thisRequest = {};
  detailController = thisRequest;
  try {
    const data = await api(`/api/errors/${encodeURIComponent(button.dataset.service)}/${encodeURIComponent(button.dataset.id)}`);
    if (detailController !== thisRequest) return;
    $('#detail-title').textContent = data.title;
    $('#detail-text').textContent = data.text;
    $('#detail-note').textContent = data.note;
    if (data.url && /^https?:\/\//.test(data.url)) {
      $('#detail-link').href = data.url;
      $('#detail-link').textContent = `Open in ${button.dataset.service === 'dagster' ? 'Dagster' : 'SigNoz'} ↗`;
      $('#detail-link').hidden = false;
    }
  } catch (error) {
    if (detailController === thisRequest) {
      $('#detail-title').textContent = 'Could not load';
      $('#detail-text').textContent = error.message;
    }
  }
}

$('#overview').addEventListener('click', event => {
  const button = event.target.closest('[data-id][data-service]');
  if (button) openDetail(button);
});

function back() {
  detailController = null;
  $('#detail').hidden = true;
  $('#overview').hidden = false;
  if (latest) render(latest);
  if (detailTrigger) Array.from($(`#${detailTrigger.service}-content`).querySelectorAll('[data-id]')).find(element => element.dataset.id === detailTrigger.id)?.focus();
}

$('#back').addEventListener('click', back);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !$('#detail').hidden) back();
});
$('#fullscreen').addEventListener('click', async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch {
    $('#connection-warning').textContent = 'Use browser fullscreen';
    $('#connection-warning').hidden = false;
  }
});
document.addEventListener('fullscreenchange', () => $('#fullscreen').setAttribute('aria-label', document.fullscreenElement ? 'Exit fullscreen' : 'Enter fullscreen'));

function clock() {
  const now = new Date();
  const parts = now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}).split(':');
  $('#clock').innerHTML = `${parts[0]}<span class="clock-colon">:</span>${parts[1]}`;
  $('#clock').dateTime = now.toISOString();
  $('#date').textContent = now.toLocaleDateString([], {weekday: 'short', day: '2-digit', month: 'short'});
}

clock();
setInterval(clock, 1000);
refresh();
