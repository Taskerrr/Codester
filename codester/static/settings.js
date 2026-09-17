import {$, api, codexTrustNotice} from './common.js';
let saved;
let dashboardApps = [];
let editingSlot = null;
let tunnelStatusRows = null;
let tunnelStatusLoading = false;
const tabs = [...document.querySelectorAll('[data-settings-tab]')];
const tabAliases = {'dashboard-layout':'display', 'ssh-tunnels':'tunnels'};
function showTab(name, focus = false) {
  name = tabAliases[name] || name;
  if (!tabs.some(tab => tab.dataset.settingsTab === name)) name = 'display';
  for (const tab of tabs) {
    const selected = tab.dataset.settingsTab === name;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    document.getElementById(tab.getAttribute('aria-controls')).hidden = !selected;
    if (selected && focus) tab.focus();
  }
  history.replaceState(null, '', `#${name}`);
  if (name === 'tunnels') refreshTunnelStatus();
}
for (const tab of tabs) {
  tab.addEventListener('click', () => showTab(tab.dataset.settingsTab));
  tab.addEventListener('keydown', event => {
    const horizontal = document.querySelector('.settings-tabs').getAttribute('aria-orientation') === 'horizontal';
    const forward = horizontal ? 'ArrowRight' : 'ArrowDown';
    const back = horizontal ? 'ArrowLeft' : 'ArrowUp';
    if (![forward, back, 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
      : (tabs.indexOf(tab) + (event.key === forward ? 1 : -1) + tabs.length) % tabs.length;
    showTab(tabs[index].dataset.settingsTab, true);
  });
}
const narrowSettings = matchMedia('(max-width: 650px)');
function orientTabs() {
  document.querySelector('.settings-tabs').setAttribute('aria-orientation', narrowSettings.matches ? 'horizontal' : 'vertical');
}
narrowSettings.addEventListener('change', orientTabs);
orientTabs();
showTab(location.hash.slice(1));
window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
for (const button of document.querySelectorAll('[data-open-settings]')) {
  button.addEventListener('click', () => showTab(button.dataset.openSettings, true));
}
function validateSettings() {
  const invalid = [...$('#settings-form').elements].find(field => field.willValidate && !field.validity.valid);
  if (!invalid) return true;
  const panel = invalid.closest('[role="tabpanel"]');
  if (panel) showTab(panel.id.replace('settings-', ''));
  const tunnel = invalid.closest('.tunnel-config');
  if (tunnel) expandTunnel(tunnel, true);
  for (let parent = invalid.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
  invalid.focus();
  invalid.reportValidity();
  return false;
}
async function refreshCodexTrustNotice() {
  try {
    const activity = await api('/api/codex/activity', {timeout:3000});
    const target = $('#codex-hook-notice');
    const markup = codexTrustNotice(activity.integration);
    if (target.innerHTML !== markup) target.innerHTML = markup;
  } catch { /* Connection errors are handled by the settings connection test. */ }
  finally { setTimeout(refreshCodexTrustNotice, 3000); }
}
refreshCodexTrustNotice();
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
    slot.querySelector('.slot-label').textContent = source ? source.textContent.trim() : 'Choose app';
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
function expandTunnel(row, open) {
  row.querySelector('.tunnel-editor').hidden = !open;
  row.querySelector('.tunnel-expand').setAttribute('aria-expanded', String(open));
}
function renderTunnelStatus(row) {
  const badge = row.querySelector('.tunnel-live-status');
  const original = saved?.tunnels.find(item => item.id === row.dataset.id);
  const fields = ['ssh_host', 'ssh_port', 'username', 'auth', 'local_port', 'remote_host', 'remote_port'];
  const changed = original && (fields.some(field => String(original[field]) !== row.querySelector(`[data-tunnel-field="${field}"]`).value)
    || row.querySelector('[data-tunnel-field="password"]').value || row.dataset.credentialSource);
  const live = tunnelStatusRows?.find(item => item.id === row.dataset.id);
  const labels = {connected:'Connected', connecting:'Connecting', reconnecting:'Reconnecting', disconnected:'Disconnected', error:'Connection failed'};
  badge.textContent = !original ? 'Not saved' : changed ? 'Unsaved changes' : tunnelStatusRows === null ? 'Status unavailable' : labels[live?.state] || 'Checking connection';
  badge.dataset.state = !original || changed ? 'draft' : live?.state || 'unknown';
  badge.title = !original || changed ? 'Save to apply this tunnel configuration.' : live?.message || 'SSH session status; does not measure traffic or database activity.';
}
async function refreshTunnelStatus() {
  if (tunnelStatusLoading || document.hidden || $('#settings-tunnels').hidden) return;
  tunnelStatusLoading = true;
  try {
    const state = await api('/api/tunnels', {timeout:4000});
    if (!Array.isArray(state.tunnels)) throw new Error('Invalid tunnel status');
    tunnelStatusRows = state.tunnels;
  } catch { tunnelStatusRows = null; }
  finally {
    tunnelStatusLoading = false;
    for (const row of document.querySelectorAll('.tunnel-config')) renderTunnelStatus(row);
  }
}
setInterval(refreshTunnelStatus, 5000);
function refreshServerChoices() {
  for (const row of document.querySelectorAll('.tunnel-config')) {
    const choice = row.querySelector('.tunnel-server-choice');
    const selected = choice.value;
    choice.replaceChildren(new Option('Choose a server', ''));
    for (const source of saved?.tunnels || []) {
      if (source.id === row.dataset.id || (source.auth === 'password' && !source.has_password)) continue;
      choice.add(new Option(`${source.name} · ${source.username}@${source.ssh_host}`, source.id));
    }
    choice.value = selected;
    row.querySelector('.tunnel-server-picker').hidden = choice.options.length === 1;
  }
}
function addTunnel(data = {}) {
  const row = $('#tunnel-template').content.firstElementChild.cloneNode(true);
  row.dataset.id = data.id || crypto.randomUUID();
  row.dataset.hasPassword = String(Boolean(data.has_password));
  if (data.credential_source) row.dataset.credentialSource = data.credential_source;
  const defaults = {name:'', ssh_host:'', username:'', ssh_port:22, auth:'password', password:'', local_port:'', remote_host:'localhost', remote_port:''};
  for (const [field, fallback] of Object.entries(defaults)) row.querySelector(`[data-tunnel-field="${field}"]`).value = data[field] ?? fallback;
  const fieldInput = name => row.querySelector(`[data-tunnel-field="${name}"]`);
  row.querySelector('.tunnel-editor').id = `tunnel-editor-${row.dataset.id}`;
  row.querySelector('.tunnel-expand').setAttribute('aria-controls', row.querySelector('.tunnel-editor').id);
  row.querySelector('.tunnel-expand').addEventListener('click', () => expandTunnel(row, row.querySelector('.tunnel-editor').hidden));
  expandTunnel(row, !data.id);
  row.querySelector('.tunnel-advanced').open = Number(fieldInput('ssh_port').value) !== 22;
  const shortcuts = [...row.querySelectorAll('[data-fill-field]')];
  const updateShortcuts = () => {
    for (const button of shortcuts) {
      const source = button.dataset.copyField;
      button.disabled = Boolean(source && (!fieldInput(source).value || !fieldInput(source).validity.valid));
    }
  };
  for (const button of shortcuts) button.addEventListener('click', () => {
    const target = fieldInput(button.dataset.fillField);
    target.value = button.dataset.copyField ? fieldInput(button.dataset.copyField).value : button.dataset.fillValue;
    target.dispatchEvent(new Event('input', {bubbles:true}));
    target.focus();
  });
  row.addEventListener('input', updateShortcuts);
  updateShortcuts();
  const auth = row.querySelector('[data-tunnel-field="auth"]');
  const password = row.querySelector('[data-tunnel-field="password"]');
  const updateAuth = () => {
    row.querySelector('.tunnel-password').hidden = auth.value !== 'password';
    row.querySelector('.tunnel-agent-note').hidden = auth.value !== 'agent';
    row.querySelector('.tunnel-auth-fields').classList.toggle('with-password', auth.value === 'password');
    const hasPassword = row.dataset.hasPassword === 'true' || Boolean(row.dataset.credentialSource);
    password.required = auth.value === 'password' && !hasPassword;
    password.placeholder = row.dataset.credentialSource ? 'Using saved server password' : hasPassword ? 'Saved · enter to replace' : 'Enter password';
  };
  const serverChoice = row.querySelector('.tunnel-server-choice');
  for (const field of ['ssh_host', 'ssh_port', 'username', 'auth']) {
    fieldInput(field).addEventListener('input', () => {
      delete row.dataset.credentialSource;
      serverChoice.value = '';
      updateAuth();
    });
  }
  auth.addEventListener('change', updateAuth);
  row.addEventListener('credential-saved', updateAuth);
  serverChoice.addEventListener('change', () => {
    const source = saved?.tunnels.find(item => item.id === serverChoice.value);
    delete row.dataset.credentialSource;
    if (source) {
      for (const field of ['ssh_host', 'ssh_port', 'username', 'auth']) fieldInput(field).value = source[field];
      password.value = '';
      if (source.auth === 'password' && source.has_password) row.dataset.credentialSource = source.id;
      row.querySelector('.tunnel-advanced').open = Number(source.ssh_port) !== 22;
      $('#save-note').textContent='Unsaved changes';
    }
    updateAuth();
    updateSummary();
  });
  updateAuth();
  const updateSummary = () => {
    const name = fieldInput('name').value || 'unnamed tunnel';
    row.setAttribute('aria-label', name);
    row.querySelector('.tunnel-summary-name').textContent = fieldInput('name').value || 'New tunnel';
    row.querySelector('.tunnel-summary-route').textContent = `${fieldInput('ssh_host').value || 'Choose host'}:${fieldInput('ssh_port').value || '22'} · :${fieldInput('local_port').value || '…'} → ${fieldInput('remote_host').value || 'localhost'}:${fieldInput('remote_port').value || '…'}`;
    row.querySelector('.test-tunnel').setAttribute('aria-label', `Test connection: ${name}`);
    row.querySelector('.duplicate-tunnel').setAttribute('aria-label', `Duplicate tunnel: ${name}`);
    row.querySelector('.remove-tunnel').setAttribute('aria-label', `Delete tunnel: ${name}`);
    renderTunnelStatus(row);
  };
  row.addEventListener('input', updateSummary);
  updateSummary();
  row.querySelector('.duplicate-tunnel').addEventListener('click', () => {
    if (document.querySelectorAll('.tunnel-config').length >= 20) { message('You can save up to 20 tunnels.', true); return; }
    const copy = {};
    for (const field of Object.keys(defaults)) copy[field] = fieldInput(field).value;
    const names = new Set([...document.querySelectorAll('[data-tunnel-field="name"]')].map(input => input.value.toLowerCase()));
    const base = (copy.name || 'Tunnel').slice(0, 65);
    copy.name = `${base} copy`;
    for (let n = 2; names.has(copy.name.toLowerCase()); n++) copy.name = `${base} copy ${n}`;
    const ports = new Set([...document.querySelectorAll('[data-tunnel-field="local_port"]')].map(input => Number(input.value)));
    let port = Number(copy.local_port) || 1023;
    do { port = port >= 65535 ? 1024 : port + 1; } while (ports.has(port));
    copy.local_port = port;
    const sourceId = row.dataset.credentialSource || row.dataset.id;
    const source = saved?.tunnels.find(item => item.id === sourceId);
    if (copy.auth === 'password' && !copy.password && source?.has_password
      && ['ssh_host', 'ssh_port', 'username', 'auth'].every(field => String(source[field]) === String(copy[field]))) copy.credential_source = source.id;
    const duplicate = addTunnel(copy);
    row.after(duplicate);
    duplicate.querySelector('[data-tunnel-field="name"]').focus();
    $('#save-note').textContent='Unsaved changes';
  });
  row.querySelector('.remove-tunnel').addEventListener('click', () => { row.remove(); $('#save-note').textContent='Unsaved changes'; });
  row.querySelector('.test-tunnel').addEventListener('click', () => testTunnel(row));
  $('#tunnel-list').append(row);
  refreshServerChoices();
  return row;
}
function addRepository(data = {}) {
  const row = $('#repository-template').content.firstElementChild.cloneNode(true);
  row.dataset.id = data.id || crypto.randomUUID();
  for (const field of ['repo','path','deploy_command']) row.querySelector(`[data-repository-field="${field}"]`).value = data[field] || '';
  const updateTitle = () => { row.querySelector('.repository-title').textContent = row.querySelector('[data-repository-field="repo"]').value || 'New repository'; };
  row.querySelector('[data-repository-field="repo"]').addEventListener('input', updateTitle);
  updateTitle();
  row.querySelector('.remove-repository').addEventListener('click', () => { row.remove(); updateRepositoryLimit(); $('#save-note').textContent='Unsaved changes'; });
  row.querySelector('.test-repository').addEventListener('click', () => testRepository(row));
  $('#repository-list').append(row);
  updateRepositoryLimit();
}
function updateRepositoryLimit() {
  $('#add-repository').disabled = document.querySelectorAll('.repository-config').length >= 3;
}
function fill(data) {
  const pg = data.postgres || {enabled:false,host:'127.0.0.1',port:5432,database:'',username:'',sslmode:'require',sslrootcert:'',refresh_seconds:10};
  $('#postgres-enabled').checked = pg.enabled;
  for (const field of ['host','port','database','username','sslmode','sslrootcert','refresh_seconds']) $(`#postgres-${field}`).value = pg[field] ?? '';
  $('#postgres-password').value = '';
  $('#postgres-clear_password').checked = false;
  $('#postgres-password-note').textContent = pg.has_password ? 'Password saved. Leave blank to keep it.' : 'Password uses the configured credential store.';
  $('#postgres-tunnel').replaceChildren(new Option('Choose a tunnel to fill host and port', ''), ...(data.tunnels || []).map(tunnel => new Option(`${tunnel.name} / localhost:${tunnel.local_port}`, String(tunnel.local_port))));
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
  $('#signoz-window_seconds').value = String(data.signoz.window_seconds || 3600);
  $('#clear-key').checked = false;
  $('#key-note').textContent = data.signoz.has_key ? 'A key is saved. Leave blank to keep it, or enter a replacement.' : 'No key saved. Use a query API key, not an ingestion key.';
  $('#github-token').value = '';
  $('#github-organization').value = data.github.organization || '';
  $('#clear-github-token').checked = false;
  $('#github-token-note').textContent = data.github.has_token ? 'Token saved · leave blank to keep it.' : 'No token saved.';
  $('#repository-list').replaceChildren();
  for (const repository of data.github.repositories || []) addRepository(repository);
  updateRepositoryLimit();
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
  data.signoz.window_seconds=Number($('#signoz-window_seconds').value);
  data.signoz.panels=[];
  for(let i=0;i<3;i++) if($(`#panel-${i}-enabled`).checked) data.signoz.panels.push({service:$(`#panel-${i}-service`).value,metric:$(`#panel-${i}-metric`).value});
  data.tunnels = Array.from(document.querySelectorAll('.tunnel-config')).map(row => ({
    id:row.dataset.id,
    name:row.querySelector('[data-tunnel-field="name"]').value,
    auth:row.querySelector('[data-tunnel-field="auth"]').value,
    password:row.querySelector('[data-tunnel-field="password"]').value,
    clear_password:false,
    credential_source:row.dataset.credentialSource || '',
    ssh_host:row.querySelector('[data-tunnel-field="ssh_host"]').value,
    username:row.querySelector('[data-tunnel-field="username"]').value,
    ssh_port:Number(row.querySelector('[data-tunnel-field="ssh_port"]').value),
    local_port:Number(row.querySelector('[data-tunnel-field="local_port"]').value),
    remote_host:row.querySelector('[data-tunnel-field="remote_host"]').value,
    remote_port:Number(row.querySelector('[data-tunnel-field="remote_port"]').value),
  }));
  data.github.token=$('#github-token').value;
  data.github.organization=$('#github-organization').value.trim();
  data.github.clear_token=$('#clear-github-token').checked;
  data.github.repositories=Array.from(document.querySelectorAll('.repository-config')).map(row => ({
    id:row.dataset.id,
    repo:row.querySelector('[data-repository-field="repo"]').value,
    path:row.querySelector('[data-repository-field="path"]').value,
    deploy_command:row.querySelector('[data-repository-field="deploy_command"]').value,
  }));
  data.postgres = {enabled:$('#postgres-enabled').checked, password:$('#postgres-password').value, clear_password:$('#postgres-clear_password').checked};
  for (const field of ['host','database','username','sslmode','sslrootcert']) data.postgres[field] = $(`#postgres-${field}`).value;
  for (const field of ['port','refresh_seconds']) data.postgres[field] = Number($(`#postgres-${field}`).value);
  return data;
}
async function saveSettings(refill = true) {
  if (!validateSettings()) throw new Error('Check the highlighted field before saving.');
  $('#save').disabled = true;
  $('#save').textContent = 'Saving…';
  try {
    saved=await api('/api/settings',{method:'PUT',body:JSON.stringify(read())});
    tunnelStatusRows = null;
    $('#settings-status').hidden = true;
    if (refill) {
      const expanded = new Set([...document.querySelectorAll('.tunnel-config')].filter(row => !row.querySelector('.tunnel-editor').hidden).map(row => row.dataset.id));
      fill(saved);
      for (const row of document.querySelectorAll('.tunnel-config')) expandTunnel(row, expanded.has(row.dataset.id));
    }
    else {
      $('#signoz-key').value='';
      $('#postgres-password').value='';
      $('#postgres-clear_password').checked=false;
      $('#postgres-password-note').textContent = saved.postgres.has_password ? 'Password saved. Leave blank to keep it.' : 'No password saved.';
      $('#github-token').value='';
      for (const row of document.querySelectorAll('.tunnel-config')) {
        const input=row.querySelector('[data-tunnel-field="password"]');
        const tunnel=saved.tunnels.find(item=>item.id === row.dataset.id);
        row.dataset.hasPassword = String(Boolean(tunnel?.has_password));
        delete row.dataset.credentialSource;
        row.querySelector('.tunnel-server-choice').value = '';
        row.dispatchEvent(new Event('credential-saved'));
        input.value='';
        input.required=row.querySelector('[data-tunnel-field="auth"]').value === 'password' && !tunnel?.has_password;
        input.placeholder=tunnel?.has_password ? 'Saved · enter to replace' : 'Enter password';
      }
      refreshServerChoices();
    }
    $('#save-note').textContent='Saved';
    refreshTunnelStatus();
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
  const chosenSlot = editingSlot;
  editingSlot = null;
  $('#app-picker').hidden = true;
  renderDashboardApps();
  document.querySelector(`[data-slot="${chosenSlot}"]`).focus();
  $('#save-note').textContent='Unsaved changes';
});
$('#add-tunnel').addEventListener('click',()=> { addTunnel(); $('#save-note').textContent='Unsaved changes'; });
$('#add-postgres-tunnel').addEventListener('click', () => {
  showTab('tunnels');
  const used = new Set([...document.querySelectorAll('[data-tunnel-field="local_port"]')].map(input => Number(input.value)));
  let localPort = 15432;
  while (used.has(localPort) && localPort < 65535) localPort++;
  const names = new Set([...document.querySelectorAll('[data-tunnel-field="name"]')].map(input => input.value.toLowerCase()));
  let name = 'PostgreSQL';
  for (let suffix = 2; names.has(name.toLowerCase()); suffix++) name = `PostgreSQL ${suffix}`;
  addTunnel({name, local_port:localPort, remote_port:5432});
  const row = $('#tunnel-list').lastElementChild;
  row.scrollIntoView({block:'start'});
  row.querySelector('[data-tunnel-field="ssh_host"]').focus();
  $('#save-note').textContent='Unsaved changes';
});
$('#add-repository').addEventListener('click',()=> { addRepository(); $('#save-note').textContent='Unsaved changes'; });
async function testTunnel(row) {
  const button = row.querySelector('.test-tunnel');
  const result = row.querySelector('.tunnel-test');
  if (!validateSettings()) return;
  expandTunnel(row, true);
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
async function testRepository(row) {
  const button=row.querySelector('.test-repository');
  const result=row.querySelector('.repository-test');
  if (!validateSettings()) return;
  button.disabled=true;
  result.textContent='Checking…';
  try {
    await saveSettings(false);
    const data=await api('/api/github/repositories',{timeout:10000});
    const repository=data.repositories.find(item=>item.id === row.dataset.id);
    result.textContent=!repository ? 'Repository check unavailable' : repository.error || `${repository.branch} · ${repository.changes} changes · ${repository.ahead ?? 'no'} ahead`;
  } catch(error) { result.textContent=error.message; }
  finally { button.disabled=false; }
}
for(const button of document.querySelectorAll('.test')) button.addEventListener('click',async()=> {
  const name=button.dataset.service;
  button.disabled=true;
  $(`#${name}-test`).textContent='Testing saved connection…';
  try { if (name === 'postgres') await saveSettings(false); const result=await api(`/api/connections/${name}/test`,{method:'POST'}); $(`#${name}-test`).textContent=result.message; }
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

$('#postgres-tunnel').addEventListener('change', () => { if ($('#postgres-tunnel').value) { $('#postgres-host').value = '127.0.0.1'; $('#postgres-port').value = $('#postgres-tunnel').value; $('#save-note').textContent = 'Unsaved changes'; } });
