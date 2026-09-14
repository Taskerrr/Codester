import {$, api} from './common.js';
let saved;
function message(text, error = false) {
  $('#settings-status').textContent = text;
  $('#settings-status').hidden = false;
  $('#settings-status').classList.toggle('error-notice', error);
}
function selectService(select, value) {
  if (!Array.from(select.options).some(option => option.value === value)) select.add(new Option(value, value));
  select.value = value;
}
function updateDashboardOptions() {
  const selects = Array.from({length:3},(_,i)=>$(`#dashboard-app-${i}`));
  const selected = selects.map(select=>select.value);
  for(const select of selects) for(const option of select.options) option.disabled = option.value !== select.value && selected.includes(option.value);
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
  $('#tunnel-list').append(row);
}
function fill(data) {
  $('#demo').checked = data.demo;
  for(let i=0;i<3;i++) $(`#dashboard-app-${i}`).value = data.dashboard_apps[i];
  updateDashboardOptions();
  for(const name of ['codex','dagster','signoz']) {
    $(`#${name}-enabled`).checked = data[name].enabled;
    if(name === 'codex') { $('#codex-activity').checked = data.codex.activity; continue; }
    for(const field of ['api_url','browser_url']) $(`#${name}-${field}`).value = data[name][field];
  }
  $('#signoz-key').value = '';
  $('#clear-key').checked = false;
  $('#key-note').textContent = data.signoz.has_key ? 'A key is saved. Leave blank to keep it, or enter a replacement.' : 'No key saved. Use a query API key, not an ingestion key.';
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
  const data = {demo:$('#demo').checked,dashboard_apps:Array.from({length:3},(_,i)=>$(`#dashboard-app-${i}`).value),codex:{enabled:$('#codex-enabled').checked, activity:$('#codex-activity').checked}};
  for(const name of ['dagster','signoz']) data[name] = {enabled:$(`#${name}-enabled`).checked,api_url:$(`#${name}-api_url`).value,browser_url:$(`#${name}-browser_url`).value};
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
  return data;
}
$('#settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  $('#save').disabled = true;
  $('#save').textContent = 'Saving…';
  try { saved=await api('/api/settings',{method:'PUT',body:JSON.stringify(read())}); fill(saved); message('Settings saved. Your dashboard is updating.'); $('#save-note').textContent='All changes saved on this machine.'; }
  catch(error) { message(error.message,true); }
  finally { $('#save').disabled=false; $('#save').textContent='Save settings'; }
});
$('#settings-form').addEventListener('input',()=> { $('#save-note').textContent='Unsaved changes'; });
for(let i=0;i<3;i++) $(`#dashboard-app-${i}`).addEventListener('change',updateDashboardOptions);
$('#add-tunnel').addEventListener('click',()=> { addTunnel(); $('#save-note').textContent='Unsaved changes'; });
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
