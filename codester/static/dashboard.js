import {$, api, escape as e, duration, ago} from './common.js';

let latest;
let detailTrigger;
let detailController;

const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const clamp = value => Math.min(100, Math.max(0, number(value)));
const empty = text => `<p class="deck-empty">${e(text)}</p>`;
const spinner = label => `<span class="loading-ring" role="img" aria-label="${e(label)}"></span>`;
const sectionHeading = (title, aside = '') => `<div class="mini-heading"><h3>${e(title)}</h3><span>${e(aside)}</span></div>`;
const utilityApps = new Set(['postgres', 'server', 'github', 'docker']);
let dockerPanelLoading = false;
let dockerControlLoading = false;
let dockerPendingStop = '';
let dockerPendingTimer;
let tunnelState;
let tunnelLoading = false;

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
    const remaining = used === null ? null : 100 - used;
    const label = window.minutes === 300 ? '5-HOUR' : window.minutes === 10080 ? 'WEEKLY' : 'USAGE';
    const reset = window.resets ? `resets ${duration(window.resets - Date.now() / 1000)}` : 'reset unavailable';
    return ring({value: remaining === null ? null : `${Math.round(remaining)}%`, label, detail: reset, progress: remaining});
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
    ${dagsterState(job.status)}
    <strong title="${e(job.title)}">${e(job.title)}</strong>
    <time>${job.status === 'QUEUED' ? 'queued' : duration(job.duration)}</time>
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

function dagsterState(status) {
  if (['STARTING', 'STARTED', 'CANCELING'].includes(status)) return spinner(status === 'CANCELING' ? 'Canceling' : 'Running');
  if (status === 'SUCCESS') return '<span class="state-mark success" aria-label="Succeeded">✓</span>';
  if (status === 'FAILURE') return '<span class="state-mark failure" aria-label="Failed">!</span>';
  if (status === 'CANCELED') return '<span class="state-mark" aria-label="Canceled">–</span>';
  return '<span class="state-mark queued" aria-label="Queued"></span>';
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

function bytes(value) {
  if (!Number.isFinite(Number(value))) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = Number(value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toLocaleString(undefined, {maximumFractionDigits: amount >= 10 ? 0 : 1})} ${units[unit]}`;
}

function applyLayout(layout) {
  const overview = $('#overview');
  for (const panel of overview.querySelectorAll('[data-app-panel]')) panel.hidden = true;
  layout.forEach(name => {
    const panel = overview.querySelector(`[data-app-panel="${name}"]`);
    if (panel) {
      panel.hidden = false;
      overview.append(panel);
    }
  });
  for (const button of document.querySelectorAll('[data-app]')) {
    button.classList.toggle('selected', layout.includes(button.dataset.app));
    button.setAttribute('aria-pressed', String(layout.includes(button.dataset.app)));
  }
}

function utilityPlaceholder(name) {
  const labels = {
    postgres: ['PostgreSQL', 'Metrics connection coming later'],
    server: ['Linux servers', 'Host metrics connection coming later'],
    github: ['GitHub', 'Repository connection coming later'],
  };
  const [label, note] = labels[name];
  return `<div class="utility-placeholder"><strong>${e(label)}</strong><span>${e(note)}</span><a href="/settings#dashboard-layout">Settings ↗</a></div>`;
}

async function refreshDockerPanel() {
  const target = $('#docker-content');
  if (!target || target.closest('.channel').hidden || dockerPanelLoading || dockerControlLoading || dockerPendingStop) return;
  dockerPanelLoading = true;
  try {
    const data = await api('/api/docker/containers', {timeout: 10000});
    $('#docker-message').innerHTML = '';
    const containers = data.containers.filter(container => container.manageable).sort(containerOrder);
    const running = containers.filter(container => container.running).length;
    const memoryUsed = containers.reduce((total, container) => total + (Number(container.memory_used) || 0), 0);
    const runningProgress = containers.length ? running / containers.length * 100 : 0;
    const memoryProgress = data.memory_limit ? memoryUsed / data.memory_limit * 100 : 0;
    target.innerHTML = `<div class="hero-rings docker-rings">
        ${ring({value:running, label:'RUNNING', detail:`${containers.length} total`, progress:runningProgress})}
        ${ring({value:bytes(memoryUsed), label:'MEMORY', detail:`${memoryProgress.toLocaleString(undefined, {maximumFractionDigits:1})}%`, progress:memoryProgress})}
      </div>
      ${sectionHeading('Containers')}
      <div class="container-mini-list">${containers.map(container => `<div class="container-mini">
        <strong title="${e(container.name)}">${e(container.name)}</strong>
        <button class="container-mini-control ${container.running ? 'stop' : 'start'}" type="button" data-docker-action="${container.running ? 'stop' : 'start'}" data-id="${e(container.id)}" aria-label="${container.running ? 'Stop' : 'Start'} ${e(container.name)}" title="${container.running ? 'Stop' : 'Start'}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 2v10"/><path d="M6.3 5.7a8 8 0 1 0 11.4 0"/></svg>
        </button>
      </div>`).join('') || empty('No containers')}</div>`;
  } catch (error) {
    target.innerHTML = `<div class="utility-placeholder"><strong>Docker unavailable</strong><span>${e(error.message)}</span><a href="/docker">Open Docker →</a></div>`;
  } finally {
    dockerPanelLoading = false;
  }
}

function containerOrder(left, right) {
  return Number(right.running) - Number(left.running) || left.name.localeCompare(right.name, undefined, {sensitivity:'base'});
}

function clearDockerConfirmation() {
  dockerPendingStop = '';
  clearTimeout(dockerPendingTimer);
  for (const button of document.querySelectorAll('.container-mini-control.confirm')) {
    button.classList.remove('confirm');
    button.title = 'Stop';
    button.setAttribute('aria-label', `Stop ${button.closest('.container-mini').querySelector('strong').textContent}`);
  }
}

async function controlDocker(button) {
  const {id, dockerAction: action} = button.dataset;
  if (action === 'stop' && dockerPendingStop !== id) {
    clearDockerConfirmation();
    dockerPendingStop = id;
    button.classList.add('confirm');
    button.title = 'Tap again to stop';
    button.setAttribute('aria-label', `Confirm stop ${button.closest('.container-mini').querySelector('strong').textContent}`);
    dockerPendingTimer = setTimeout(clearDockerConfirmation, 4000);
    return;
  }
  clearDockerConfirmation();
  dockerControlLoading = true;
  button.disabled = true;
  button.classList.add('working');
  try {
    await api(`/api/docker/containers/${encodeURIComponent(id)}/${action}`, {method:'POST', timeout:20000});
    dockerControlLoading = false;
    await refreshDockerPanel();
  } catch (error) {
    dockerControlLoading = false;
    $('#docker-message').innerHTML = `<p>${e(error.message)}</p>`;
    button.disabled = false;
    button.classList.remove('working');
  }
}

function render(snapshot) {
  const layout = snapshot.layout || ['codex', 'dagster', 'signoz'];
  applyLayout(layout);
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
  for (const name of layout.filter(name => utilityApps.has(name) && name !== 'docker')) {
    $(`#${name}-content`).innerHTML = utilityPlaceholder(name);
  }
  if (layout.includes('docker')) refreshDockerPanel();
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
  const dockerButton = event.target.closest('[data-docker-action]');
  if (dockerButton && !dockerButton.disabled) {
    controlDocker(dockerButton);
    return;
  }
  const button = event.target.closest('[data-id][data-service]');
  if (button) openDetail(button);
});

$('.deck-buttons').addEventListener('click', event => {
  const button = event.target.closest('[data-app]');
  if (!button) return;
  const panel = document.querySelector(`[data-app-panel="${button.dataset.app}"]:not([hidden])`);
  if (panel) panel.querySelector('.channel-arrow').focus();
  else window.location.assign('/settings#dashboard-layout');
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

function showTunnelStatus(data) {
  tunnelState = data;
  const button = $('#tunnels');
  const count = data.tunnels?.length || 0;
  const connected = data.tunnels?.filter(tunnel => tunnel.state === 'connected').length || 0;
  const labels = {
    unconfigured:'Set up SSH tunnels',
    disconnected:`Connect ${count} SSH tunnel${count === 1 ? '' : 's'}`,
    connecting:`Connecting ${count} SSH tunnel${count === 1 ? '' : 's'}`,
    reconnecting:`Reconnecting SSH tunnels`,
    partial:`${connected} of ${count} SSH tunnels connected`,
    connected:`Disconnect ${count} SSH tunnel${count === 1 ? '' : 's'}`,
    error:'Retry SSH tunnels',
  };
  const label = labels[data.state] || 'SSH tunnel error';
  button.dataset.state = data.state;
  button.setAttribute('aria-label', label);
  button.setAttribute('aria-checked', String(Boolean(data.desired)));
  const stateNames = {connected:'Connected',connecting:'Connecting',reconnecting:'Reconnecting',disconnected:'Off',error:'Failed'};
  const summary = data.state === 'connected'
    ? `All ${count} connected`
    : data.state === 'partial'
      ? `${connected} of ${count} connected`
      : data.state === 'unconfigured'
        ? 'No connections configured'
        : stateNames[data.state] || label;
  const rows = (data.tunnels || []).map(tunnel => `<li><span title="${e(tunnel.name)}">${e(tunnel.name)}</span><b class="${e(tunnel.state)}">${e(stateNames[tunnel.state] || tunnel.state)}</b></li>`).join('');
  $('#tunnel-tooltip').innerHTML = `<strong>SSH tunnels</strong><span>${e(summary)}</span>${rows ? `<ul>${rows}</ul>` : ''}`;
  const problem = data.tunnels?.find(tunnel => tunnel.message)?.message;
  $('#tunnel-warning').hidden = !problem;
  $('#tunnel-warning').textContent = problem ? `SSH · ${problem}` : '';
}

async function refreshTunnels() {
  try {
    showTunnelStatus(await api('/api/tunnels', {timeout:5000}));
  } catch {
    $('#tunnels').dataset.state = 'error';
    $('#tunnel-tooltip').innerHTML = '<strong>SSH tunnels</strong><span>Status unavailable</span>';
    $('#tunnel-warning').textContent = 'Could not read SSH tunnel status';
    $('#tunnel-warning').hidden = false;
  } finally {
    setTimeout(refreshTunnels, document.hidden ? 15000 : 5000);
  }
}

$('#tunnels').addEventListener('click', async () => {
  if (tunnelLoading) return;
  if (!tunnelState || tunnelState.state === 'unconfigured') {
    window.location.assign('/settings#ssh-tunnels');
    return;
  }
  tunnelLoading = true;
  $('#tunnels').dataset.state = 'connecting';
  try {
    const retry = ['error','partial'].includes(tunnelState.state);
    const action = tunnelState.desired && !retry ? 'disconnect' : 'connect';
    showTunnelStatus(await api(`/api/tunnels/${action}`, {method:'POST', timeout:15000}));
  } catch (error) {
    $('#tunnels').dataset.state = 'error';
    $('#tunnels').setAttribute('aria-label', error.message);
    $('#tunnel-tooltip').innerHTML = `<strong>SSH tunnels</strong><span>${e(error.message)}</span>`;
    $('#tunnel-warning').textContent = error.message;
    $('#tunnel-warning').hidden = false;
  } finally {
    tunnelLoading = false;
  }
});

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
refreshTunnels();
