import {$, api} from './common.js';
let saved;
let dashboardApps = [];
let editingSlot = null;
function message(text, error = false) {
  $('#settings-status').textContent = text;
  $('#settings-status').hidden = false;
  $('#settings-status').classList.toggle('error-notice', error);
}
function selectService(select, value) {
  if (!Array.from(select.options).some(option => option.value === value)) select.add(new Option(value, value));
  select.value = value;
}
function renderDashboardApps() {
  for (const slot of document.querySelectorAll('.column-slot')) {
    const index = Number(slot.dataset.slot);
    const app = dashboardApps[index];
    const source = app ? document.querySelector(`[data-app-choice="${app}"]`) : null;
    const glyph = slot.querySelector('.slot-glyph');
    glyph.replaceChildren(source ? source.firstElementChild.cloneNode(true) : document.createTextNode('+'));
    slot.classList.toggle('editing', editingSlot === index);
    slot.title = source ? source.textContent.trim() : 'Choose an app';
    slot.setAttribute('aria-label', `Column ${index + 1}: ${source ? source.textContent.trim() : 'empty'}`);
  }
  for (const choice of document.querySelectorAll('[data-app-choice]')) {
    const selectedAt = dashboardApps.indexOf(choice.dataset.appChoice);
    choice.classList.toggle('selected', selectedAt >= 0);
    choice.disabled = selectedAt >= 0 && selectedAt !== editingSlot;
  }
}
function addTunnel(data = {}) {
  const row = $('#tunnel-template').content.firstElementChild.cloneNode(true);
  row.dataset.id = data.id || crypto.randomUUID();
  const defaults = {name:'', ssh_host:'', username:'', ssh_port:22, auth:'agent', password:'', local_port:'', remote_host:'127.0.0.1', remote_port:''};
  for (const [field, fallback] of Object.entries(defaults)) row.querySelector(`[data-tunnel-field="${field}"]`).value = data[field] ?? fallback;
  const auth = row.querySelector('[data-tunnel-field="auth"]');
  const password = row.querySelector('[data-tunnel-field="password"]');
  const updateAuth = () => {
    row.querySelector('.tunnel-password').hidden = auth.value !== 'password';
    password.required = auth.value === 'password' && !data.has_password;
    password.placeholder = data.has_password ? 'Saved · enter to replace' : 'Enter password';
  };
  auth.addEventListener('change', updateAuth);
  updateAuth();
  row.querySelector('.tunnel-title').textContent = data.name || 'New forward';
  row.querySelector('[data-tunnel-field="name"]').addEventListener('input', event => { row.querySelector('.tunnel-title').textContent = event.target.value || 'New forward'; });
  row.querySelector('.remove-tunnel').addEventListener('click', () => { row.remove(); $('#save-note').textContent='Unsaved changes'; });
  row.querySelector('.test-tunnel').addEventListener('click', () => testTunnel(row));
  $('#tunnel-list').append(row);
}
function fill(data) {
  $('#demo').checked = data.demo;
  dashboardApps = [...data.dashboard_apps];
  editingSlot = null;
  $('#app-picker').hidden = true;
  renderDashboardApps();
  for(const name of ['codex','dagster','signoz','github']) {
    $(`#${name}-enabled`).checked = data[name].enabled;
    if(name === 'codex') { $('#codex-activity').checked = data.codex.activity; continue; }
    for(const field of ['api_url','browser_url']) $(`#${name}-${field}`).value = data[name][field];
  }
  $('#signoz-key').value = '';
  $('#clear-key').checked = false;
  $('#key-note').textContent = data.signoz.has_key ? 'A key is saved. Leave blank to keep it, or enter a replacement.' : 'No key saved. Use a query API key, not an ingestion key.';
  $('#github-token').value = '';
  $('#clear-github-token').checked = false;
  $('#github-token-note').textContent = data.github.has_token ? 'Token saved · leave blank to keep it.' : 'No token saved.';
  for(let i=0;i<3;i++) {
    const panel = data.signoz.panels[i];
    $(`#panel-${i}-enabled`).checked = Boolean(panel);
    selectService($(`#panel-${i}-service`),panel?.service || '');
    $(`#panel-${i}-metric`).value = panel?.metric || ['request_rate','error_rate','p95'][i];
  }
  selectService($('#error-service'),data.signoz.error_service);
  $('#tunnel-list').replaceChildren();
  for (const tunnel of data.tunnels || []) addTunnel(tunnel);
}
function read() {
  const data = {demo:$('#demo').checked,dashboard_apps:[...dashboardApps],codex:{enabled:$('#codex-enabled').checked, activity:$('#codex-activity').checked}};
  for(const name of ['dagster','signoz','github']) data[name] = {enabled:$(`#${name}-enabled`).checked,api_url:$(`#${name}-api_url`).value,browser_url:$(`#${name}-browser_url`).value};
  data.signoz.api_key=$('#signoz-key').value;
  data.signoz.clear_key=$('#clear-key').checked;
  data.signoz.error_service=$('#error-service').value;
  data.signoz.panels=[];
  for(let i=0;i<3;i++) if($(`#panel-${i}-enabled`).checked) data.signoz.panels.push({service:$(`#panel-${i}-service`).value,metric:$(`#panel-${i}-metric`).value});
  data.tunnels = Array.from(document.querySelectorAll('.tunnel-config')).map(row => ({
    id:row.dataset.id,
    name:row.querySelector('[data-tunnel-field="name"]').value,
    auth:row.querySelector('[data-tunnel-field="auth"]').value,
    password:row.querySelector('[data-tunnel-field="password"]').value,
    clear_password:false,
    ssh_host:row.querySelector('[data-tunnel-field="ssh_host"]').value,
    username:row.querySelector('[data-tunnel-field="username"]').value,
    ssh_port:Number(row.querySelector('[data-tunnel-field="ssh_port"]').value),
    local_port:Number(row.querySelector('[data-tunnel-field="local_port"]').value),
    remote_host:row.querySelector('[data-tunnel-field="remote_host"]').value,
    remote_port:Number(row.querySelector('[data-tunnel-field="remote_port"]').value),
  }));
  data.github.token=$('#github-token').value;
  data.github.clear_token=$('#clear-github-token').checked;
  return data;
}
async function saveSettings(refill = true) {
  $('#save').disabled = true;
  $('#save').textContent = 'Saving…';
  try {
    saved=await api('/api/settings',{method:'PUT',body:JSON.stringify(read())});
    if (refill) fill(saved);
    else {
      $('#signoz-key').value='';
      $('#github-token').value='';
      for (const row of document.querySelectorAll('.tunnel-config')) {
        const input=row.querySelector('[data-tunnel-field="password"]');
        const tunnel=saved.tunnels.find(item=>item.id === row.dataset.id);
        input.value='';
        input.required=row.querySelector('[data-tunnel-field="auth"]').value === 'password' && !tunnel?.has_password;
        input.placeholder=tunnel?.has_password ? 'Saved · enter to replace' : 'Enter password';
      }
    }
    $('#save-note').textContent='Saved';
    return saved;
  } finally {
    $('#save').disabled=false;
    $('#save').textContent='Save settings';
  }
}
$('#settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await saveSettings(); message('Settings saved.'); }
  catch(error) { message(error.message,true); }
});
$('#settings-form').addEventListener('input',()=> { $('#save-note').textContent='Unsaved changes'; });
for (const slot of document.querySelectorAll('.column-slot')) slot.addEventListener('click', () => {
  editingSlot = Number(slot.dataset.slot);
  $('#app-picker').hidden = false;
  renderDashboardApps();
  $('#app-picker').querySelector('button:not(:disabled)')?.focus();
});
for (const choice of document.querySelectorAll('[data-app-choice]')) choice.addEventListener('click', () => {
  if (editingSlot === null) return;
  const app = choice.dataset.appChoice;
  const existing = dashboardApps.indexOf(app);
  if (existing >= 0 && existing !== editingSlot) [dashboardApps[editingSlot], dashboardApps[existing]] = [dashboardApps[existing], dashboardApps[editingSlot]];
  else dashboardApps[editingSlot] = app;
  editingSlot = null;
  $('#app-picker').hidden = true;
  renderDashboardApps();
  $('#save-note').textContent='Unsaved changes';
});
$('#add-tunnel').addEventListener('click',()=> { addTunnel(); $('#save-note').textContent='Unsaved changes'; });
async function testTunnel(row) {
  const button = row.querySelector('.test-tunnel');
  const result = row.querySelector('.tunnel-test');
  if (!$('#settings-form').reportValidity()) return;
  button.disabled = true;
  result.textContent = 'Testing…';
  try {
    await saveSettings(false);
    const response = await api(`/api/tunnels/${encodeURIComponent(row.dataset.id)}/test`, {method:'POST', timeout:25000});
    result.textContent = response.message;
  } catch (error) {
    result.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}
for(const button of document.querySelectorAll('.test')) button.addEventListener('click',async()=> {
  const name=button.dataset.service;
  button.disabled=true;
  $(`#${name}-test`).textContent='Testing saved connection…';
  try { const result=await api(`/api/connections/${name}/test`,{method:'POST'}); $(`#${name}-test`).textContent=result.message; }
  catch(error) { $(`#${name}-test`).textContent=error.message; }
  finally { button.disabled=false; }
});
$('#discover').addEventListener('click',async()=> {
  $('#discover').disabled=true;
  $('#discovery-status').textContent='Finding services using the saved connection…';
  try {
    const data=await api('/api/signoz/services',{method:'POST'});
    for(const select of document.querySelectorAll('.service-select')) {
      const previous=select.value;
      select.replaceChildren(new Option('All services',''));
      for(const service of data.services) select.add(new Option(service,service));
      selectService(select,previous);
    }
    $('#discovery-status').textContent=`${data.services.length} services found. ${data.note}`;
  } catch(error) { $('#discovery-status').textContent=error.message; }
  finally { $('#discover').disabled=false; }
});
async function init() {
  $('#save').disabled=true;
  try { saved=await api('/api/settings'); fill(saved); $('#save').disabled=false; }
  catch(error) { message(`Could not load settings: ${error.message}. Reload before editing.`,true); }
}
init();
