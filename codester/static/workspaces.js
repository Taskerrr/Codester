import {$, api, escape as e} from './common.js';
import {initSQLWorkspace} from './sql-workspace.js';

const labels = {codex:'Codex', dagster:'Dagster', signoz:'SigNoz', postgres:'PostgreSQL', server:'Linux servers', docker:'Docker', github:'GitHub'};
// Register dedicated views here; other apps expand their existing overview panel.
const workspaceViews = {postgres:{element:$('#sql-workspace'), initialize:initSQLWorkspace}};
let selected = 'home';
let homeLayout = ['codex', 'dagster', 'signoz'];
let pickerTrigger;
let saving = false;
let epoch = 0;
export const layoutEpoch = () => epoch;
export const activeWorkspace = () => selected;
export const currentLayout = () => [...homeLayout];

export function applyWorkspaceLayout(layout = homeLayout) {
  homeLayout = [...layout];
  const overview = $('#overview');
  overview.classList.toggle('workspace-open', selected !== 'home');
  for (const panel of overview.querySelectorAll('[data-app-panel]')) {
    panel.hidden = selected === 'home' ? !homeLayout.includes(panel.dataset.appPanel) : Object.hasOwn(workspaceViews, selected) || panel.dataset.appPanel !== selected;
    panel.classList.toggle('focused-workspace', selected === panel.dataset.appPanel);
    panel.querySelector('[data-picker]').disabled = selected !== 'home';
  }
  if (selected === 'home') {
    const visible = [...overview.querySelectorAll('[data-app-panel]:not([hidden])')].map(panel => panel.dataset.appPanel);
    if (visible.join() !== homeLayout.join()) for (const name of homeLayout) overview.append($(`[data-app-panel="${name}"]`));
  }
  for (const [name, view] of Object.entries(workspaceViews)) view.element.hidden = selected !== name;
  $('#workspace-home').setAttribute('aria-pressed', String(selected === 'home'));
  for (const button of document.querySelectorAll('.deck-buttons [data-app]')) {
    button.classList.toggle('selected', selected === button.dataset.app);
    button.setAttribute('aria-pressed', String(selected === button.dataset.app));
  }
}

function selectWorkspace(name) {
  selected = Object.hasOwn(labels, name) ? name : 'home';
  closePicker(false);
  $('#detail').hidden = true;
  $('#overview').hidden = false;
  applyWorkspaceLayout();
  document.dispatchEvent(new CustomEvent('workspacechange', {detail:selected}));
}
function navigate(name) {
  const hash = name === 'home' ? '#home' : `#workspace/${name}`;
  if (location.hash === hash) selectWorkspace(name);
  else location.hash = hash;
}
function readLocation() { selectWorkspace(location.hash.startsWith('#workspace/') ? location.hash.split('/')[1] : 'home'); }

function closePicker(focus = true) {
  $('#panel-picker').hidden = true;
  if (pickerTrigger) {
    pickerTrigger.setAttribute('aria-expanded', 'false');
    if (focus) pickerTrigger.focus({preventScroll:true});
  }
}
function openPicker(trigger) {
  if (selected !== 'home' || saving) return;
  if (pickerTrigger === trigger && !$('#panel-picker').hidden) { closePicker(); return; }
  closePicker(false);
  pickerTrigger = trigger;
  trigger.setAttribute('aria-expanded', 'true');
  $('#panel-picker-error').textContent = '';
  $('#panel-picker-options').innerHTML = Object.entries(labels).map(([name,label]) => {
    const current = name === trigger.dataset.picker;
    const occupied = homeLayout.includes(name) && !current;
    const icon = $(`.deck-buttons [data-app="${name}"]`).innerHTML;
    return `<button type="button" data-replace="${name}" ${occupied || current ? 'disabled' : ''}>${icon}<span>${e(label)}</span><small>${occupied ? 'Already shown' : current ? 'Current' : ''}</small></button>`;
  }).join('');
  const popup = $('#panel-picker');
  popup.hidden = false;
  // Anchor positioning via a stylesheet rule works with the app's strict CSP.
  const rect = trigger.getBoundingClientRect();
  const rule = [...document.styleSheets].find(sheet => sheet.href?.endsWith('/workspaces.css'));
  if (rule) {
    if (popup.dataset.rule) rule.deleteRule(Number(popup.dataset.rule));
    const index = rule.cssRules.length;
    rule.insertRule(`#panel-picker { left:${Math.max(8, Math.min(rect.left, innerWidth - 328))}px; top:${Math.max(8, Math.min(rect.bottom + 8, innerHeight - popup.offsetHeight - 8))}px; }`, index);
    popup.dataset.rule = String(index);
  }
  popup.querySelector('button:not(:disabled)')?.focus();
}
$('#panel-picker-options').addEventListener('click', async event => {
  const button = event.target.closest('[data-replace]');
  if (!button || saving) return;
  const previous = pickerTrigger.dataset.picker;
  const next = homeLayout.map(name => name === previous ? button.dataset.replace : name);
  saving = true;
  epoch += 1;
  for (const option of $('#panel-picker').querySelectorAll('button')) option.disabled = true;
  try {
    const response = await api('/api/dashboard/layout', {method:'PUT', body:JSON.stringify({apps:next})});
    applyWorkspaceLayout(response.layout);
    closePicker(false);
    $(`[data-picker="${button.dataset.replace}"]`).focus({preventScroll:true});
    document.dispatchEvent(new CustomEvent('layoutchange', {detail:response.layout}));
  } catch (error) {
    $('#panel-picker-error').textContent = error.message;
    for (const option of $('#panel-picker-options').querySelectorAll('button')) option.disabled = homeLayout.includes(option.dataset.replace);
  } finally { saving = false; epoch += 1; $('#panel-picker-close').disabled = false; }
});
$('#panel-picker-close').addEventListener('click', () => closePicker());
$('#overview').addEventListener('click', event => {
  const picker = event.target.closest('[data-picker]');
  if (picker) openPicker(picker);
  const link = event.target.closest('a[href="/postgres"], a[href="/postgres#locks"]');
  if (link) { event.preventDefault(); navigate('postgres'); }
});
document.addEventListener('click', event => {
  if (!$('#panel-picker').hidden && !event.target.closest('#panel-picker, [data-picker]')) closePicker(false);
});
$('#panel-picker').addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closePicker(); return; }
  const buttons = [...$('#panel-picker').querySelectorAll('button:not(:disabled)')];
  const index = buttons.indexOf(document.activeElement);
  let next;
  if (event.key === 'ArrowDown') next = (index + 1) % buttons.length;
  if (event.key === 'ArrowUp') next = (index - 1 + buttons.length) % buttons.length;
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = buttons.length - 1;
  if (event.key === 'Tab') next = (index + (event.shiftKey ? -1 : 1) + buttons.length) % buttons.length;
  if (next !== undefined) { event.preventDefault(); buttons[next]?.focus(); }
});
$('#workspace-home').addEventListener('click', () => navigate('home'));
$('.deck-buttons').addEventListener('click', event => {
  const button = event.target.closest('[data-app]');
  if (button) navigate(button.dataset.app);
});
window.addEventListener('hashchange', readLocation);
window.addEventListener('resize', () => closePicker(false));
for (const view of Object.values(workspaceViews)) view.initialize();
readLocation();
