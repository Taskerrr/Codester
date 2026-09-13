import {$, api, escape as e} from './common.js';

let pendingStop = '';
let pendingTimer;
let loading = false;

function summary(data) {
  const stopped = data.total - data.running;
  $('#docker-summary').innerHTML = `<div><strong>${data.running}</strong><span>RUNNING</span></div><div><strong>${stopped}</strong><span>STOPPED</span></div><div><strong>${data.total}</strong><span>TOTAL</span></div>`;
}

function render(data) {
  summary(data);
  $('#docker-status').textContent = 'Connected';
  $('#docker-status').dataset.state = 'connected';
  $('#docker-updated').textContent = 'just now';
  $('#container-list').innerHTML = data.containers.length ? data.containers.map(container => `<article class="container-row">
    <i class="container-state" data-running="${container.running}" aria-label="${e(container.state)}"></i>
    <div class="container-name"><strong title="${e(container.name)}">${e(container.name)}</strong><span title="${e(container.image)}">${e(container.image)}</span></div>
    <div class="container-detail"><strong>${e(container.status)}</strong><span>${e(container.ports || 'No published ports')}</span></div>
    <button class="container-action ${container.running ? 'stop' : 'start'}" type="button" data-id="${e(container.id)}" data-action="${container.running ? 'stop' : 'start'}">${container.running ? 'Stop' : 'Start'}</button>
  </article>`).join('') : '<p class="docker-empty">No containers</p>';
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
    button.textContent = 'Stop';
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
    button.textContent = 'Confirm stop';
    pendingTimer = setTimeout(clearConfirmation, 4000);
    return;
  }
  clearConfirmation();
  button.disabled = true;
  button.textContent = action === 'start' ? 'Starting…' : 'Stopping…';
  try {
    await api(`/api/docker/containers/${encodeURIComponent(id)}/${action}`, {method: 'POST', timeout: 20000});
    await load();
  } catch (error) {
    $('#docker-status').textContent = error.message;
    $('#docker-status').dataset.state = 'error';
    button.disabled = false;
    button.textContent = action === 'start' ? 'Start' : 'Stop';
  }
});

$('#docker-refresh').addEventListener('click', load);
load();
setInterval(() => {
  if (!document.hidden && !pendingStop) load();
}, 5000);
