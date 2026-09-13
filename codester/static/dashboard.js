import {$, api, escape as e, duration, ago} from './common.js';
let latest;
let detailTrigger;
let detailController;
const histories = new Map();
let historyMode;
let historyRevision;
const sampleSeries = [
  [22,25,24,29,23,21,26,33,30,27,35,40,36,30,33,44,41,38,43,39,48,44,40,43],
  [1.1,.8,.9,.6,.9,.8,.7,1.2,1.8,1.1,.9,1,1.4,1.1,.9,1.2,1.7,2.3,1.4,1.1,.8,1.24],
  [160,170,155,163,152,169,183,173,162,166,197,180,170,185,201,188,174,165,182,174,195,186],
];
const heading = (title, aside = '') => `<div class="mini-heading"><h3>${e(title)}</h3><span>${e(aside)}</span></div>`;
const empty = (text) => `<p class="deck-empty">${e(text)}</p>`;
const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const spinner = (label) => `<span class="loading-ring" role="img" aria-label="${e(label)}"></span>`;
function graph(values, label, variant = '') {
  const valid = values.filter(Number.isFinite);
  if (!valid.length) return `<div class="sparkline no-readings" aria-label="No readings"><span>—</span></div>`;
  const low = Math.min(...valid), high = Math.max(...valid);
  const range = high-low || Math.max(1, high*.2);
  const points = values.map((v,i) => Number.isFinite(v) ? [4+i*232/Math.max(values.length-1,1), 44-(v-low)/range*34] : null);
  const path = points.map((p,i) => p ? `${i && points[i-1] ? 'L':'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}` : '').join(' ');
  const last = points.filter(Boolean).at(-1);
  return `<svg class="sparkline ${variant}" viewBox="0 0 240 54" preserveAspectRatio="none" role="img" aria-label="${e(label)}"><path class="graph-baseline" d="M0 49H240"/><path class="graph-line" d="${path}"/><circle class="graph-point" cx="${last[0]}" cy="${last[1]}" r="2.6"/></svg>`;
}
function observe(key, value, stamp, demoValues) {
  if(latest.demo) return demoValues;
  let history = histories.get(key);
  if(!history) { history=[]; histories.set(key,history); }
  if(stamp && history.at(-1)?.stamp!==stamp) {
    history.push({stamp,value:Number.isFinite(value)?value:null});
    if(history.length>30) history.shift();
  }
  return history.map(point=>point.value);
}
function errors(name, rows) {
  return rows.length ? `<div class="deck-errors">${rows.map(row=>`<button class="deck-error" type="button" data-service="${name}" data-id="${e(row.id)}"><span class="failure-mark" aria-label="Failed">!</span><span class="error-title">${e(row.title)}</span><time>${ago(row.timestamp)}</time><span class="error-chevron" aria-hidden="true">›</span></button>`).join('')}</div>` : '<span class="clear-mark" aria-label="No errors">✓</span>';
}
function codex(data) {
  const windows=data.windows.map(window=>{
    const used=Number.isFinite(window.used)?Math.min(100,Math.max(0,window.used)):null;
    const label=window.minutes===300?'5-hour':window.minutes===10080?'Weekly':window.minutes?duration(window.minutes*60):'Usage';
    const blocks=Array.from({length:40},(_,i)=>`<rect x="${i*10}" y="0" width="7" height="18" rx="1" class="${used!==null && i<used*.4?'meter-lit':'meter-track'}"/>`).join('');
    return `<div class="limit"><div class="limit-label"><span>${e(label)}</span><strong>${used??'—'}<small>%</small></strong></div><svg class="block-meter" viewBox="0 0 400 18" preserveAspectRatio="none" role="img" aria-label="${e(label)}: ${used??'unavailable'} percent used">${blocks}</svg><span class="reset-time" title="Resets in"><span aria-hidden="true">↻</span> ${window.resets?duration(window.resets-Date.now()/1000):'—'}</span></div>`;
  }).join('');
  return `<div class="limits">${windows||empty('Usage unavailable')}</div>${heading('Recent')}<div class="recent-tasks">${data.tasks.map(task=>`<div class="recent-task"><span class="task-tick" aria-hidden="true">↳</span><div><strong title="${e(task.title)}">${e(task.title)}</strong><small>${e(task.project)}</small></div><time>${ago(task.timestamp)}</time></div>`).join('')||empty('No recent tasks')}</div>`;
}
function dagster(data, stamp) {
  const running=number(data.running), queued=number(data.queued), total=running+queued;
  const queueValues=observe('dagster:queue',queued,stamp,[2,2,3,5,4,3,2,2,4,6,5,4,3,5,6,4,3,4]);
  const width=total?running/total*400:0;
  return `<div class="run-summary"><div class="run-count"><strong>${running}</strong><span>${running?spinner('Jobs running'):''} running</span></div><div class="queue-count"><strong>${queued}</strong><span>queued</span></div>${graph(queueValues,'Observed queue depth','queue-graph')}</div><svg class="queue-meter" viewBox="0 0 400 5" preserveAspectRatio="none" role="img" aria-label="${running} running, ${queued} queued"><rect class="meter-track" width="400" height="5" rx="2"/><rect class="queue-fill" x="${width}" width="${total?400-width:0}" height="5"/><rect class="meter-lit" width="${width}" height="5"/></svg><div class="queue-age">${queued?`Oldest ${duration(data.oldest)}`:'Queue clear'}</div><div class="running-jobs">${data.jobs.map(job=>`<div class="running-job">${job.status==='STARTED'?spinner('Running'):spinner(job.status.toLowerCase())}<strong title="${e(job.title)}">${e(job.title)}</strong>${job.status!=='STARTED'?`<small>${e(job.status.toLowerCase())}</small>`:''}<time>${duration(job.duration)}</time></div>`).join('')||empty('Idle')}</div>${heading('Errors',data.errors.length?String(data.errors.length):'')}${errors('dagster',data.errors)}${data.queue?.length?`<details class="queued-jobs"><summary>Queue <span>${queued}</span></summary><ul>${data.queue.map(job=>`<li>${e(job.title)}</li>`).join('')}</ul></details>`:''}`;
}
function signoz(data, stamp) {
  return `<div class="signal-metrics">${data.panels.map((panel,index)=>{
    const key=`signoz:${index}:${panel.service}:${panel.metric}`;
    const values=observe(key,panel.value,stamp,sampleSeries[index%sampleSeries.length]);
    return `<div class="signal-metric"><div class="signal-label"><span>${e(panel.label)}</span><small>${e(panel.service||'All services')}</small></div><div class="signal-value"><strong>${panel.value==null?'—':Number(panel.value).toLocaleString(undefined,{maximumFractionDigits:2})}</strong><span>${e(panel.unit)}</span></div>${graph(values,`${panel.label}, recent observed readings`)}</div>`;
  }).join('')||empty('No measurements')}</div>${heading('Errors','15m')}${errors('signoz',data.errors)}`;
}
const renderers={codex,dagster,signoz};
function render(snapshot) {
  if(historyMode!==snapshot.demo || historyRevision!==snapshot.revision) { histories.clear(); historyMode=snapshot.demo; historyRevision=snapshot.revision; }
  $('#mode').textContent=snapshot.demo?'DEMO':'';
  $('#mode').title=snapshot.demo?'Sample data':'';
  const codexState=snapshot.services.codex;
  const dagsterState=snapshot.services.dagster;
  const signozState=snapshot.services.signoz;
  const railValues=[['codex',codexState,`${codexState.data?.windows[0]?.used??'—'}%`,'Codex usage'],['dagster',dagsterState,dagsterState.data?.running??'—','Dagster running'],['signoz',signozState,signozState.data?.errors.length??'—','Recent SigNoz errors']];
  $('#quick-stats').innerHTML=railValues.map(([name,state,value,label])=>`<div class="quick-stat ${name}" title="${label}" aria-label="${label}: ${e(value)}${['stale','error'].includes(state.status)?', stale':''}"><img src="/static/${name}.svg" alt=""><span>${e(value)}</span><i class="health-dot" data-state="${e(state.status)}" aria-hidden="true"></i></div>`).join('');
  for(const [name,state] of Object.entries(snapshot.services)) {
    const status=$(`#${name}-status`);
    status.closest('.channel').dataset.state=state.status;
    const issue=['error','stale'].includes(state.status);
    status.dataset.state=state.status;
    status.textContent=issue?(state.status==='stale'?'Stale':'Offline'):'';
    const freshness=state.last_success?`Updated ${ago(state.last_success)}`:'No reading yet';
    status.title=`${state.status} · ${freshness}`;
    status.setAttribute('aria-label',`${name}: ${state.status}. ${freshness}`);
    const message=$(`#${name}-message`);
    message.innerHTML=issue?`<details><summary>${state.last_success?`Last read ${ago(state.last_success)}`:'Connection failed'}</summary><p>${e(state.message)}</p></details>`:'';
    const target=$(`#${name}-content`);
    const active=document.activeElement;
    const focusedId=target.contains(active)?active.dataset.id:null;
    const queueOpen=target.querySelector('details')?.open;
    const scrollTop=target.scrollTop;
    target.innerHTML=state.data?renderers[name](state.data,state.last_success):state.status==='loading'?spinner('Loading'):empty(state.status==='disabled'?'Not connected':'No data')+'<a class="connect-link" href="/settings">Connect ↗</a>';
    if(queueOpen&&target.querySelector('details')) target.querySelector('details').open=true;
    target.scrollTop=scrollTop;
    if(focusedId) Array.from(target.querySelectorAll('[data-id]')).find(el=>el.dataset.id===focusedId)?.focus({preventScroll:true});
  }
}
async function refresh() {
  try {
    latest=await api('/api/dashboard',{timeout:8000});
    $('#connection-warning').hidden=true;
    if($('#detail').hidden) render(latest);
  } catch {
    $('#connection-warning').textContent='Disconnected · readings paused';
    $('#connection-warning').hidden=false;
  } finally { setTimeout(refresh,document.hidden?15000:5000); }
}
async function openDetail(button) {
  detailTrigger={service:button.dataset.service,id:button.dataset.id};
  $('#overview').hidden=true;
  $('#detail').hidden=false;
  $('#detail-title').textContent='Loading…';
  $('#detail-source').textContent=button.dataset.service;
  $('#detail-title').focus();
  $('#detail-text').textContent='';
  $('#detail-note').textContent='';
  $('#detail-link').hidden=true;
  const thisRequest={};
  detailController=thisRequest;
  try {
    const data=await api(`/api/errors/${encodeURIComponent(button.dataset.service)}/${encodeURIComponent(button.dataset.id)}`);
    if(detailController!==thisRequest) return;
    $('#detail-title').textContent=data.title;
    $('#detail-text').textContent=data.text;
    $('#detail-note').textContent=data.note;
    if(data.url&&/^https?:\/\//.test(data.url)) {
      $('#detail-link').href=data.url;
      $('#detail-link').textContent=`Open in ${button.dataset.service==='dagster'?'Dagster':'SigNoz'} ↗`;
      $('#detail-link').hidden=false;
    }
  } catch(error) { if(detailController===thisRequest) { $('#detail-title').textContent='Could not load'; $('#detail-text').textContent=error.message; } }
}
$('#overview').addEventListener('click',event=>{ const button=event.target.closest('[data-id][data-service]'); if(button) openDetail(button); });
function back() {
  detailController=null;
  $('#detail').hidden=true;
  $('#overview').hidden=false;
  if(latest) render(latest);
  if(detailTrigger) Array.from($(`#${detailTrigger.service}-content`).querySelectorAll('[data-id]')).find(el=>el.dataset.id===detailTrigger.id)?.focus();
}
$('#back').addEventListener('click',back);
document.addEventListener('keydown',event=>{ if(event.key==='Escape'&&!$('#detail').hidden) back(); });
$('#fullscreen').addEventListener('click',async()=>{
  try { if(document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
  catch { $('#connection-warning').textContent='Use browser fullscreen'; $('#connection-warning').hidden=false; }
});
document.addEventListener('fullscreenchange',()=>$('#fullscreen').setAttribute('aria-label',document.fullscreenElement?'Exit fullscreen':'Enter fullscreen'));
function clock() {
  const now=new Date();
  const parts=now.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',hour12:false}).split(':');
  $('#clock').innerHTML=`${parts[0]}<span class="clock-colon">:</span>${parts[1]}`;
  $('#clock').dateTime=now.toISOString();
  $('#date').textContent=now.toLocaleDateString([],{weekday:'short',day:'2-digit',month:'short'});
}
clock(); setInterval(clock,1000); refresh();
