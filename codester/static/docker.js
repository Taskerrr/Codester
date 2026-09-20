import {$, api, escape as e} from './common.js';
import {DockerGroups} from './docker-groups.js';

const groups = new DockerGroups($('#container-list'), (message, error) => {
  $('#docker-action-result').textContent = message;
  $('#docker-action-result').classList.toggle('error', error);
}, load);
let loading = false;

function bytes(value) {
  if (!Number.isFinite(Number(value))) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = Number(value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toLocaleString(undefined, {maximumFractionDigits: amount >= 10 ? 0 : 1})} ${units[unit]}`;
}

const percent = value => Number.isFinite(Number(value)) ? `${Number(value).toLocaleString(undefined, {maximumFractionDigits: 1})}%` : '—';

function summary(data, containers) {
  const running = containers.filter(container => container.running).length;
  const memoryUsed = containers.reduce((total, container) => total + (Number(container.memory_used) || 0), 0);
  const runningProgress = containers.length ? running / containers.length * 100 : 0;
  const memoryProgress = data.memory_limit ? memoryUsed / data.memory_limit * 100 : 0;
  $('#docker-summary').innerHTML = `${gauge(running, 'RUNNING', `${containers.length} total`, runningProgress)}${gauge(bytes(memoryUsed), 'MEMORY', percent(memoryProgress), memoryProgress)}`;
}

function gauge(value, label, detail, progress) {
  const safeProgress = Math.min(100, Math.max(0, Number(progress) || 0));
  return `<div class="docker-gauge"><div class="docker-ring">
    <svg viewBox="0 0 120 120" aria-hidden="true"><circle class="docker-ring-track" cx="60" cy="60" r="51" pathLength="100"/><circle class="docker-ring-progress" cx="60" cy="60" r="51" pathLength="100" stroke-dasharray="${safeProgress} 100"/></svg>
    <div><strong>${e(value)}</strong><span>${e(label)}</span></div>
  </div><small>${e(detail)}</small></div>`;
}

function render(data) {
  const containers = data.containers.filter(container => container.manageable);
  summary(data, containers);
  $('#docker-status').textContent = 'Connected';
  $('#docker-status').dataset.state = 'connected';
  $('#docker-updated').textContent = 'just now';
  const focusKey = document.activeElement?.dataset.dockerKey;
  $('#container-list').innerHTML = groups.markup(data.groups);
  groups.restoreFocus(focusKey);
}

async function load() {
  if (loading || groups.paused) return;
  loading = true;
  $('#docker-refresh').disabled = true;
  try {
    const data = await api('/api/docker/containers', {timeout: 10000});
    if (!groups.paused) render(data);
  } catch (error) {
    $('#docker-status').textContent = 'Unavailable';
    $('#docker-status').dataset.state = 'error';
    $('#container-list').innerHTML = `<div class="docker-error"><strong>Docker Desktop unavailable</strong><p>${e(error.message)}</p><p>Start Docker Desktop, then refresh. Native Codester startup can use the local Docker CLI directly.</p></div>`;
  } finally {
    loading = false;
    $('#docker-refresh').disabled = false;
  }
}

$('#docker-refresh').addEventListener('click', load);
load();
setInterval(() => {
  if (!document.hidden && !groups.paused) load();
}, 5000);
