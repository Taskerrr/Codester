import {$, api, escape as e} from './common.js';

let pendingStop = '';
let pendingTimer;
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
  const containers = data.containers.filter(container => container.manageable).sort(containerOrder);
  summary(data, containers);
  $('#docker-status').textContent = 'Connected';
  $('#docker-status').dataset.state = 'connected';
  $('#docker-updated').textContent = 'just now';
  $('#container-list').innerHTML = containers.length ? containers.map(container => `<article class="container-row">
    <div class="container-name"><strong title="${e(container.name)}">${e(container.name)}</strong><span title="${e(container.image)}">${e(container.image)}</span></div>
    <button class="container-action ${container.running ? 'stop' : 'start'}" type="button" data-id="${e(container.id)}" data-action="${container.running ? 'stop' : 'start'}" aria-label="${container.running ? 'Stop' : 'Start'} ${e(container.name)}" title="${container.running ? 'Stop' : 'Start'}">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 2v10"/><path d="M6.3 5.7a8 8 0 1 0 11.4 0"/></svg>
    </button>
  </article>`).join('') : '<p class="docker-empty">No containers</p>';
}

function containerOrder(left, right) {
  return Number(right.running) - Number(left.running) || left.name.localeCompare(right.name, undefined, {sensitivity:'base'});
}

async function load() {
  if (loading) return;
  loading = true;
  $('#docker-refresh').disabled = true;
  try {
    const data = await api('/api/docker/containers', {timeout: 10000});
    render(data);
  } catch (error) {
    $('#docker-status').textContent = 'Unavailable';
    $('#docker-status').dataset.state = 'error';
    $('#container-list').innerHTML = `<div class="docker-error"><strong>Docker Desktop unavailable</strong><p>${e(error.message)}</p><p>Start Docker Desktop, then refresh. Native Codester startup can use the local Docker CLI directly.</p></div>`;
  } finally {
    loading = false;
    $('#docker-refresh').disabled = false;
  }
}

function clearConfirmation() {
  pendingStop = '';
  clearTimeout(pendingTimer);
  for (const button of document.querySelectorAll('.container-action.confirm')) {
    button.classList.remove('confirm');
    button.title = 'Stop';
  }
}

$('#container-list').addEventListener('click', async event => {
  const button = event.target.closest('.container-action');
  if (!button || button.disabled) return;
  const {id, action} = button.dataset;
  if (action === 'stop' && pendingStop !== id) {
    clearConfirmation();
    pendingStop = id;
    button.classList.add('confirm');
    button.title = 'Tap again to stop';
    pendingTimer = setTimeout(clearConfirmation, 4000);
    return;
  }
  clearConfirmation();
  button.disabled = true;
  button.classList.add('working');
  try {
    await api(`/api/docker/containers/${encodeURIComponent(id)}/${action}`, {method: 'POST', timeout: 20000});
    await load();
  } catch (error) {
    $('#docker-status').textContent = error.message;
    $('#docker-status').dataset.state = 'error';
    button.disabled = false;
    button.classList.remove('working');
  }
});

$('#docker-refresh').addEventListener('click', load);
load();
setInterval(() => {
  if (!document.hidden && !pendingStop) load();
}, 5000);
