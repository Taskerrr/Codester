import {$, api} from './common.js';

let data = {services:[], hosts:[], actions:{}};
let selected = location.hash.slice(1);
let editing = false;
let draftId;
let pendingCommand;
let viewSignature = '';
let navSignature = '';
let submitting = false;
const current = () => data.services.find(service => service.id === selected);
function message(text = '') { $('#service-message').textContent = text; $('#service-message').hidden = !text; }
function show() {
  if (!current()) selected = data.services[0]?.id || '';
  const signature = JSON.stringify([selected, data.services.map(service => [service.id, service.name])]);
  if (signature !== navSignature) {
    navSignature = signature;
    $('#services-list').replaceChildren(...data.services.map(service => {
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = service.name; button.setAttribute('aria-current', String(service.id === selected));
      button.addEventListener('click', () => { if (editing) { message('Save or cancel your edits first.'); return; } selected = service.id; history.replaceState(null, '', `#${selected}`); pendingCommand = null; $('#command-confirmation').hidden = true; show(); });
      return button;
    }));
  }
  if (editing) return;
  const service = current();
  $('#service-view').hidden = !service;
  $('#service-empty').hidden = Boolean(service);
  if (!service) return;
  const host = data.hosts.find(host => host.id === service.host_id);
  const next = JSON.stringify([service, host, data.dagster_url]);
  if (next !== viewSignature) {
    viewSignature = next;
    $('#service-name').textContent = service.name;
    $('#service-target').textContent = `${host ? `${host.username}@${host.ssh_host}:${host.ssh_port}` : 'SSH connection missing'} / ${service.path}`;
    $('#service-notes').textContent = service.notes;
    $('#service-source').hidden = !data.dagster_url || !/dagster/i.test(service.name);
    if (data.dagster_url) $('#service-source').href = data.dagster_url;
    $('#service-commands').replaceChildren(...service.commands.map(command => {
      const row = document.createElement('div'); row.className = 'service-command';
      const copy = document.createElement('div'); const label = document.createElement('strong'); label.textContent = command.label;
      const script = document.createElement('pre'); script.textContent = command.script; copy.append(label, script);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'quiet-button'; button.textContent = 'Run'; button.setAttribute('aria-label', `Run ${command.label}`);
      button.addEventListener('click', () => {
        if (command.confirm) { pendingCommand = command.id; $('#confirmation-copy').textContent = `${command.label} on ${host?.ssh_host || 'server'}\n${command.script}`; $('#command-confirmation').hidden = false; $('#confirm-command').focus(); }
        else run(command.id);
      });
      row.append(copy, button); return row;
    }));
  }
  const action = data.actions[selected];
  const busy = submitting || action?.state === 'running';
  document.querySelectorAll('#service-commands button, #compare-service, #edit-service, #confirm-command').forEach(button => button.disabled = busy);
  $('#service-output').hidden = !action;
  if (action) {
    $('#output-name').textContent = action.label;
    $('#output-state').textContent = {running:'Running',success:'Finished',error:'Failed',unknown:'Outcome unknown'}[action.state] || action.state;
    $('#output-state').dataset.state = action.state;
    $('#output-context').textContent = `${action.host} / ${action.path} / ${new Date(action.started_at * 1000).toLocaleString()}`;
    $('#output-script').textContent = action.script;
    const log = $('#output-log');
    const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
    if (log.textContent !== action.output) { log.textContent = action.output || ''; if (atEnd) log.scrollTop = log.scrollHeight; }
    $('#output-message').textContent = `${action.message}${action.truncated ? ' Showing the last 64 KB of output.' : ''}`;
  }
}
async function refresh() {
  try { data = await api('/api/services'); show(); }
  catch (error) { message(error.message); }
}
async function run(command, confirmed = false) {
  if (submitting || data.actions[selected]?.state === 'running') return;
  const identifier = selected;
  submitting = true; message(); show();
  try {
    data.actions[identifier] = await api(`/api/services/${identifier}/run/${command}`, {method:'POST', body:JSON.stringify({confirmed})});
    $('#command-confirmation').hidden = true;
  } catch (error) { message(error.message); }
  finally { submitting = false; show(); }
}
function addCommand(command = {}) {
  const row = $('#command-editor-template').content.firstElementChild.cloneNode(true);
  row.dataset.id = command.id || crypto.randomUUID();
  for (const field of ['label','script']) row.querySelector(`[data-field=${field}]`).value = command[field] || '';
  row.querySelector('[data-field=confirm]').checked = Boolean(command.confirm);
  row.querySelector('.remove-command').addEventListener('click', () => row.remove());
  $('#command-editors').append(row);
}
function edit(service) {
  editing = true; draftId = service?.id || crypto.randomUUID(); message();
  $('#service-view').hidden = true; $('#service-empty').hidden = true; $('#service-editor').hidden = false;
  $('#editor-title').textContent = service ? 'Edit service' : 'Add service';
  for (const field of ['name','path','branch','notes']) $(`#edit-${field}`).value = service?.[field] || (field === 'branch' ? 'main' : '');
  $('#edit-host').replaceChildren(...data.hosts.map(host => new Option(`${host.name} / ${host.username}@${host.ssh_host}`, host.id)));
  if (service) $('#edit-host').value = service.host_id;
  $('#command-editors').replaceChildren(); for (const command of service?.commands || []) addCommand(command);
  $('#delete-service').hidden = !service;
  $('#edit-name').focus();
}
$('#new-service').addEventListener('click', () => { if (!editing) edit(); });
$('#edit-service').addEventListener('click', () => edit(current()));
$('#cancel-edit').addEventListener('click', () => { editing = false; $('#service-editor').hidden = true; show(); });
$('#add-command').addEventListener('click', () => addCommand());
$('#compare-service').addEventListener('click', () => run('git-status'));
$('#confirm-command').addEventListener('click', () => { if (pendingCommand) run(pendingCommand, true); });
$('#cancel-command').addEventListener('click', () => { pendingCommand = null; $('#command-confirmation').hidden = true; });
$('#service-editor').addEventListener('submit', async event => {
  event.preventDefault();
  const service = {host_id:$('#edit-host').value, commands:[...document.querySelectorAll('.command-editor')].map(row => ({id:row.dataset.id, label:row.querySelector('[data-field=label]').value, script:row.querySelector('[data-field=script]').value, confirm:row.querySelector('[data-field=confirm]').checked}))};
  for (const field of ['name','path','branch','notes']) service[field] = $(`#edit-${field}`).value;
  const button = $('#service-editor [type=submit]'); button.disabled = true;
  try { await api(`/api/services/${draftId}`, {method:'PUT',body:JSON.stringify(service)}); selected = draftId; editing = false; $('#service-editor').hidden = true; message(); await refresh(); }
  catch (error) { message(error.message); }
  finally { button.disabled = false; }
});
$('#delete-service').addEventListener('click', async () => {
  try { await api(`/api/services/${draftId}`, {method:'DELETE'}); editing = false; $('#service-editor').hidden = true; await refresh(); }
  catch (error) { message(error.message); }
});
await refresh();
async function poll() { if (!document.hidden && !submitting) await refresh(); setTimeout(poll, 2000); }
setTimeout(poll, 2000);
