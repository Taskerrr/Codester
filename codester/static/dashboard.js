import {$, api, escape as e, duration, ago, compactTime} from './common.js';
import {applyWorkspaceLayout, activeWorkspace, currentLayout, layoutEpoch, navigate} from './workspaces.js';
import {DockerGroups} from './docker-groups.js';
import {GitHubUpdates} from './github-updates.js';
import {openHomeLog} from './signoz-logs.js';

let latest;
let snapshotReceivedAt = 0;
let dashboardConnected = false;
let detailTrigger;
let detailController;

const number = value => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
const clamp = value => Math.min(100, Math.max(0, number(value)));
const empty = text => `<p class="deck-empty">${e(text)}</p>`;
const spinner = label => `<span class="loading-ring" role="img" aria-label="${e(label)}"></span>`;
const sectionHeading = (title, aside = '') => `<div class="mini-heading"><h3>${e(title)}</h3><span>${e(aside)}</span></div>`;
const utilityApps = new Set(['server', 'docker']);
let dockerPanelLoading = false;
const dockerMessage = $('#docker-message');
const dockerGroups = new DockerGroups($('#docker-content'), (message, error) => {
  dockerMessage.textContent = message;
  dockerMessage.classList.toggle('error', error);
}, refreshDockerPanel);
let tunnelState;
let tunnelLoading = false;
let tunnelMutation = 0;
let repositoryOperations = new Map();
let repositoriesLoading = false;
let signozHomeLogs;
let signozHomeMode = 'overview';
let signozHomeLoading = false;
let signozHomeTimer;
let pendingHomeLog;
const githubUpdates = new GitHubUpdates(redrawGithub, () => activeWorkspace() === 'github');
function redrawGithub() {
  const target = $('#github-content');
  const active = document.activeElement;
  const focused = target.contains(active) ? {id:active.dataset.id, action:active.dataset.githubUpdate} : null;
  const scroll = target.scrollTop;
  const logs = [...target.querySelectorAll('.repo-update-log')].map(node => node.scrollTop);
  target.innerHTML = github(latest?.services?.github?.data || {});
  target.scrollTop = scroll;
  target.querySelectorAll('.repo-update-log').forEach((node, index) => { node.scrollTop = logs[index] || 0; });
  if (focused) [...target.querySelectorAll('[data-github-update]')].find(node => node.dataset.id === focused.id && node.dataset.githubUpdate === focused.action)?.focus({preventScroll:true});
}
let codexActivitySignature = '';
let liveCodexActivity;

function ring({value, label, detail = '', insideDetail = '', progress = 0, live = false}) {
  const safeProgress = live ? 92 : clamp(progress);
  const display = value === null || value === undefined ? '—' : e(value);
  return `<div class="metric-ring ${live ? 'reading-ring' : ''}">
    <div class="ring-visual">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle class="ring-track" cx="60" cy="60" r="51" pathLength="100"/>
        <circle class="ring-progress" cx="60" cy="60" r="51" pathLength="100" stroke-dasharray="${safeProgress} 100"/>
      </svg>
      <div class="ring-value"><strong>${display}</strong><span>${e(label)}</span>${insideDetail ? `<small class="ring-reset">${e(insideDetail)}</small>` : ''}</div>
    </div>
    <small>${e(detail)}</small>
  </div>`;
}

// Preserve SVG nodes and in-flight animations across snapshot/activity renders.
function renderMetrics(target, html) {
  const previous = [...target.querySelectorAll('.ring-progress')].map(circle => ({
    circle, label: circle.closest('.metric-ring').querySelector('.ring-value span').textContent,
    progress: getComputedStyle(circle).strokeDasharray,
  }));
  target.innerHTML = html;
  target.querySelectorAll('.ring-progress').forEach((circle, index) => {
    const old = previous[index];
    if (!old || old.label !== circle.closest('.metric-ring').querySelector('.ring-value span').textContent) return;
    const next = circle.getAttribute('stroke-dasharray');
    const changed = next !== old.circle.getAttribute('stroke-dasharray');
    circle.replaceWith(old.circle);
    if (!changed) return;
    old.circle.getAnimations().forEach(animation => animation.cancel());
    old.circle.setAttribute('stroke-dasharray', next);
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      old.circle.animate([
        {strokeDasharray: old.progress}, {strokeDasharray: next},
      ], {duration: 750, easing: 'cubic-bezier(.22, 1, .36, 1)'});
    }
  });
}

const jobLabel = title => String(title ?? '').replaceAll('_', ' ');

function errors(name, rows, limit = 3) {
  if (!rows.length) return '<div class="all-clear"><span>✓</span> Clear</div>';
  return `<div class="deck-errors">${rows.slice(0, limit).map(row => `<button class="deck-error" type="button" data-service="${name}" data-id="${e(row.id)}">
    <span class="failure-mark" aria-label="Failed">!</span>
    <span class="error-title" title="${e(row.title)}">${e(name === 'dagster' ? jobLabel(row.title) : row.title)}</span>
    <time title="${ago(row.timestamp)}">${compactTime(row.timestamp)}</time>
  </button>`).join('')}</div>`;
}

function codex(data) {
  const windows = data.windows.slice(0, 2).map(window => {
    const used = Number.isFinite(window.used) ? clamp(window.used) : null;
    const remaining = used === null ? null : 100 - used;
    const label = window.minutes === 300 ? '5-HOUR' : window.minutes === 10080 ? 'WEEKLY' : 'USAGE';
    const reset = window.resets ? duration(window.resets - Date.now() / 1000) : '—';
    return ring({value: remaining === null ? null : `${Math.round(remaining)}%`, label, insideDetail: reset, progress: remaining});
  }).join('');
  const tasks = data.tasks.slice(0, 3).map(task => `<div class="recent-row codex-task ${task.inferred_active ? 'active' : ''}">
    <span class="codex-task-marker">${task.inferred_active ? spinner('Active Codex turn') : ['limited', 'error'].includes(task.activity_state) ? `<span class="state-mark stopped" aria-label="${e(task.status)}">!</span>` : task.activity_state === 'stopped' ? '<span class="state-mark stopped" aria-label="Stopped">–</span>' : '<span class="state-mark success" aria-label="Idle">✓</span>'}</span>
    <div><strong title="${e(task.project)}">${e(task.project)}</strong><small title="${e(task.title)}">${e(task.title)}</small>${['limited', 'error'].includes(task.activity_state) ? `<small class="task-failure">${e(task.status)}</small>` : ''}</div>
    ${task.inferred_active ? '' : `<time title="${ago(task.timestamp)}">${compactTime(task.timestamp)}</time>`}
  </div>`).join('');
  return `<div class="hero-rings codex-rings">${windows || empty('Usage unavailable')}</div>
    ${sectionHeading('Recent activity')}
    <div class="recent-list">${tasks || empty('No recent activity')}</div>`;
}

function dagster(data) {
  const running = number(data.running);
  const queued = number(data.queued);
  const total = running + queued;
  const jobs = data.jobs.slice(0, 3).map(job => `<button type="button" class="compact-row dagster-job" data-service="dagster" data-id="${e(job.id)}" aria-label="View run: ${e(jobLabel(job.title))}">
    ${dagsterState(job.status)}
    <strong title="${e(job.title)}">${e(jobLabel(job.title))}</strong>
    <time>${job.status === 'QUEUED' ? 'queued' : duration(job.duration)}</time>
  </button>`).join('');
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

function shortUser(value) {
  const user = String(value || '');
  return user.length > 14 ? `${user.slice(0, 6)}â€¦${user.slice(-4)}` : user;
}

function signozHomeFeed(data, mode) {
  const title = mode === 'errors' ? 'Latest errors' : 'Latest logs';
  if (!data) {
    return `${sectionHeading(title, 'Connecting')}
      <div class="home-log-list" aria-label="${e(title)}">${Array.from({length:6}, () => '<span class="home-log-skeleton" aria-hidden="true"></span>').join('')}</div>`;
  }
  const healthy = ['connected', 'demo'].includes(data.status);
  const freshness = data.last_success ? `${data.status === 'stale' ? 'Stale Â· ' : data.status === 'demo' ? 'Demo Â· ' : 'Live Â· '}${ago(data.last_success)}` : data.status === 'disabled' ? 'Not connected' : 'Unavailable';
  const rows = data.rows.map(row => {
    const request = row.request || {};
    const message = String(row.body || '').split('\n')[0] || '(empty message)';
    const requestText = [request.method, request.path].filter(Boolean).join(' ') || message;
    const signal = request.status || row.severity || 'LOG';
    const numericStatus = Number(request.status);
    const problem = ['ERROR','FATAL','CRITICAL'].includes(String(row.severity).toUpperCase()) || (Number.isFinite(numericStatus) && numericStatus >= 400);
    const app = row.app || 'Unknown app';
    const user = shortUser(row.user_id);
    const label = [compactTime(row.timestamp), app, row.user_id ? `user ${row.user_id}` : '', signal, requestText].filter(Boolean).join(', ');
    return `<button class="home-log-row ${problem ? 'is-error' : ''}" type="button" data-home-log-id="${e(row.id)}" data-id="${e(row.id)}" aria-label="${e(label)}">
      <span class="home-log-meta"><time>${e(compactTime(row.timestamp))}</time><strong title="${e(app)}">${e(app)}</strong>${user ? `<span class="home-log-user" title="${e(row.user_id)}">${e(user)}</span>` : ''}</span>
      <span class="home-log-request"><b>${e(signal)}</b><span title="${e(requestText)}">${e(requestText)}</span></span>
    </button>`;
  }).join('');
  const emptyMessage = healthy ? (mode === 'errors' ? 'No recent errors' : 'No recent logs') : data.message || 'Logs unavailable';
  return `${sectionHeading(title, freshness)}
    <div class="home-log-list" aria-label="${e(title)}">${rows || empty(emptyMessage)}</div>`;
}

function signoz(data, homeContent = 'overview', homeLogs = undefined) {
  if (activeWorkspace() === 'home' && homeContent !== 'overview') return signozHomeFeed(homeLogs, homeContent);
  const panels = data.panels || [];
  const requestRate = panels.find(panel => panel.metric === 'request_count') || selectPanel(panels, 'request_rate', 0);
  const latency = selectPanel(panels, 'p95', requestRate === panels[0] ? 1 : 0);
  const apps = data.top_apps || [];
  const requests = app => number(app.requests ?? app.rate * (data.window_seconds || 900));
  const peak = Math.max(...apps.map(requests), 1);
  const appRows = apps.map(app => `<div class="app-row">
    <div><strong title="${e(app.service)}">${e(app.service)}</strong><svg class="app-bar" viewBox="0 0 100 2" preserveAspectRatio="none" aria-hidden="true"><rect width="${requests(app) / peak * 100}" height="2"/></svg></div>
    <b>${requests(app).toLocaleString(undefined, {maximumFractionDigits: 0})} <small>requests</small></b>
  </div>`).join('');
  return `<div class="hero-rings signoz-rings">${reading(requestRate, 'Request rate')}${reading(latency, 'p95 latency')}</div>
    <div class="split-lists signoz-lists">
      <section>${sectionHeading('Requests by app', data.window_label || '15 min')}<div class="app-list">${appRows || empty(data.top_apps_message || 'No requests in this window')}</div></section>
      <section>${sectionHeading('Errors', data.window_label || '15 min')}${errors('signoz', data.errors)}</section>
    </div>`;
}

function sparkline(values) {
  const safe = values.map(number);
  const peak = Math.max(...safe, 1);
  const points = safe.map((value, index) => {
    const x = safe.length === 1 ? 70 : index / (safe.length - 1) * 140;
    return `${x.toFixed(1)},${(30 - value / peak * 25).toFixed(1)}`;
  }).join(' ');
  return `<svg class="repo-spark" viewBox="0 0 140 34" preserveAspectRatio="none" aria-hidden="true">
    <polyline class="repo-spark-fill" points="0,34 ${points} 140,34"/>
    <polyline class="repo-spark-line" points="${points}"/>
  </svg>`;
}

function github(data) {
  const days = (data.days || []).slice(-182);
  const peak = Math.max(...days.map(day => number(day.count)), 1);
  const calendar = days.map(day => {
    const count = number(day.count);
    const level = count ? Math.max(1, Math.ceil(count / peak * 4)) : 0;
    return `<span class="contribution-day level-${level}" title="${e(day.date)} · ${count} contribution${count === 1 ? '' : 's'}" aria-label="${e(day.date)}: ${count} contributions"></span>`;
  }).join('');
  let previousMonth = '';
  const monthStarts = days.map((day, index) => {
    const date = new Date(`${day.date}T00:00:00Z`);
    const key = `${date.getUTCFullYear()}-${date.getUTCMonth()}`;
    if (key === previousMonth) return null;
    previousMonth = key;
    return {date, index};
  }).filter(Boolean);
  if (monthStarts.length > 1 && monthStarts[1].index < 21) monthStarts.shift();
  const monthColumns = new Map(monthStarts.map(({date, index}) => [Math.floor(index / 7), date]));
  const months = Array.from({length:26}, (_, column) => {
    const date = monthColumns.get(column);
    return date ? `<span title="${date.toLocaleString([], {month:'long', year:'numeric', timeZone:'UTC'})}">${date.toLocaleString([], {month:'short', timeZone:'UTC'})}</span>` : '<span></span>';
  }).join('');
  const repoRows = [...(data.repositories || []).slice(0, 3)];
  const workspace = activeWorkspace() === 'github';
  if (workspace) for (const row of githubUpdates.rows) {
    if (!repoRows.some(repo => repo.name.toLowerCase() === row.repo.toLowerCase())) repoRows.push({name:row.repo,url:row.url});
  }
  const repositories = repoRows.map(repository => {
    const local = repositoryOperations.get(repository.name.toLowerCase()) || repository.local;
    const action = local?.action || {state:'idle'};
    const running = action.state === 'running';
    const meta = local ? repositoryMeta(local) : ago(repository.pushed_at);
    const statusText = running ? action.message : ['success','error'].includes(action.state) ? `${action.message} · ${meta}` : meta;
    const controls = `<div class="repo-actions">${local ? `
      <button type="button" class="${local.demo ? 'demo-preview' : ''}" data-repository-action="push" data-id="${e(local.id)}" ${local.demo || running || !local.needs_push ? 'disabled' : ''} aria-label="Push ${e(repository.name)}" title="${local.needs_push ? 'Push committed changes' : 'Nothing to push'}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 16V3m0 0L7 8m5-5 5 5"/><path d="M5 14v5h14v-5"/></svg></button>
      <button type="button" class="deploy ${local.deploy_state === 'needed' ? 'needed' : ''} ${local.demo ? 'demo-preview' : ''}" data-repository-action="deploy" data-id="${e(local.id)}" ${local.demo || running || !local.deploy_configured || local.deploy_state === 'current' ? 'disabled' : ''} aria-label="Deploy ${e(repository.name)}" title="${local.deploy_configured ? local.deploy_state === 'current' ? 'Already deployed' : 'Deploy current commit' : 'No deploy command'}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M14 4c3-1 5-1 6-1 0 1 0 3-1 6l-6 6-4-4 5-7Z"/><path d="m9 11-4 1-2 2 6 1m4 0-1 4-2 2-1-6"/><path d="M6 18c-2 0-3 1-3 3 2 0 3-1 3-3Z"/></svg></button>
    ` : ''}${workspace ? githubUpdates.controls(repository.name) : ''}</div>`;
    return `<div class="repo-row ${running ? 'working' : ''}">
      <a class="repo-copy" href="${e(repository.url)}" target="_blank" rel="noopener noreferrer" title="${e(statusText)}"><strong title="${e(repository.name)}">${e(repository.name)}</strong>${local ? `<small>${e(statusText)}</small>` : ''}</a>
      ${repository.commits ? sparkline(repository.commits) : '<span></span>'}
      <b>${repository.commits ? repository.commits.reduce((total, count) => total + number(count), 0) : '—'}</b>
      <time class="repo-time" title="${ago(repository.pushed_at)}">${compactTime(repository.pushed_at)}</time>
      ${controls}
      ${workspace ? githubUpdates.detail(repository.name) : ''}
    </div>`;
  }).join('');
  return `<div class="github-hero">
      ${!days.length && data.calendar_loading ? (data.calendar_error ? empty('History unavailable; retrying') : spinner('Loading contribution history in the background')) : `<div class="contribution-wrap" title="${e(data.calendar_error || '')}"><div class="contribution-months">${months}</div><div class="contribution-grid">${calendar}</div></div>`}
    </div>
    ${sectionHeading('Recent repositories', data.organization || data.login || '')}
    <div class="repo-list">${repositories || empty('No repositories')}</div>`;
}

function repositoryMeta(local) {
  if (local.error) return 'CHECKOUT UNAVAILABLE';
  const parts = [local.branch || 'detached'];
  if (local.changes) parts.push(`${local.changes} change${local.changes === 1 ? '' : 's'}`);
  if (local.ahead) parts.push(`↑${local.ahead}`);
  if (local.behind) parts.push(`↓${local.behind}`);
  if (local.deploy_state === 'needed') parts.push('deploy');
  if (local.deploy_state === 'unknown') parts.push('deploy ?');
  return parts.join(' · ');
}

function postgres(data) {
  const rows = (data.queries || []).slice(0, 4).map(row => `<a href="/postgres" class="pg-mini-row"><span><strong>${e(row.query || 'Query hidden by permissions')}</strong><small>PID ${row.pid} / ${e(row.username || '')} / ${e(row.state || '')}</small></span><time>${duration(row.query_seconds)}</time></a>`).join('');
  const blocking = (data.blocking || []).slice(0, 3).map(edge => `<a class="pg-mini-block" href="/postgres#locks">PID ${edge.waiting_pid} waiting for ${edge.blocking_pid ? `PID ${edge.blocking_pid}` : 'prepared transaction'}</a>`).join('');
  return `<div class="pg-counts"><div><strong>${number(data.active)}</strong><span>ACTIVE${data.hidden_sessions ? ' (VISIBLE)' : ''}</span></div><div class="${data.waiting ? 'pg-waiting' : ''}"><strong>${number(data.waiting)}</strong><span>WAITING</span></div></div>${sectionHeading('Queries', data.database)}${rows || empty(data.hidden_sessions ? 'Some queries hidden by permissions' : 'No active queries')}${sectionHeading('Blocking locks', `${number(data.held_locks)} held`)}${blocking || empty(data.hidden_sessions ? 'Limited visibility' : 'No blocking sessions observed')}<a href="/postgres" class="connect-link">View activity</a>`;
}
const renderers = {codex, dagster, signoz, github, postgres};

function signozHomeVisible() {
  return activeWorkspace() === 'home' && !document.hidden && currentLayout().includes('signoz') && signozHomeMode !== 'overview';
}

function redrawSignozHome() {
  if (!latest || !signozHomeVisible()) return;
  const target = $('#signoz-content');
  const focusedId = target.contains(document.activeElement) ? document.activeElement.dataset.id : null;
  const scrollTop = target.scrollTop;
  renderMetrics(target, signoz(latest.services.signoz.data || {}, signozHomeMode, signozHomeLogs));
  target.scrollTop = scrollTop;
  if (focusedId) target.querySelector(`[data-id="${CSS.escape(focusedId)}"]`)?.focus({preventScroll:true});
}

async function refreshSignozHome() {
  clearTimeout(signozHomeTimer);
  if (!signozHomeVisible()) {
    signozHomeTimer = setTimeout(refreshSignozHome, 5000);
    return;
  }
  if (signozHomeLoading) return;
  signozHomeLoading = true;
  const requestedMode = signozHomeMode;
  try {
    const params = new URLSearchParams({mode:requestedMode, seconds:'900', limit:'6'});
    const data = await api(`/api/signoz/logs?${params}`, {timeout:20000});
    if (requestedMode !== signozHomeMode || !signozHomeVisible()) return;
    signozHomeLogs = data;
    redrawSignozHome();
  } catch (error) {
    if (requestedMode === signozHomeMode && signozHomeVisible()) {
      signozHomeLogs = {
        ...(signozHomeLogs || {rows:[], last_success:null, mode:requestedMode}),
        status:signozHomeLogs?.last_success ? 'stale' : 'error',
        message:`Logs unavailable. ${error.message}`,
      };
      redrawSignozHome();
    }
  } finally {
    signozHomeLoading = false;
    signozHomeTimer = setTimeout(refreshSignozHome, 5000);
  }
}

function bytes(value) {
  if (!Number.isFinite(Number(value))) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let amount = Number(value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toLocaleString(undefined, {maximumFractionDigits: amount >= 10 ? 0 : 1})} ${units[unit]}`;
}


function utilityPlaceholder(name) {
  const labels = {
    postgres: ['PostgreSQL', 'Metrics connection coming later'],
    server: ['Linux servers', 'Host metrics connection coming later'],
  };
  const [label, note] = labels[name];
  return `<div class="utility-placeholder"><strong>${e(label)}</strong><span>${e(note)}</span><a href="/settings#dashboard-layout">Settings ↗</a></div>`;
}

async function refreshDockerPanel() {
  const target = $('#docker-content');
  if (!target || target.closest('.channel').hidden || dockerPanelLoading || dockerGroups.paused) return;
  dockerPanelLoading = true;
  try {
    const data = await api('/api/docker/containers', {timeout: 10000});
    if (dockerGroups.paused) return;
    const focusKey = document.activeElement?.dataset.dockerKey;
    const containers = data.containers.filter(container => container.manageable);
    const running = containers.filter(container => container.running).length;
    const memoryUsed = containers.reduce((total, container) => total + (Number(container.memory_used) || 0), 0);
    const runningProgress = containers.length ? running / containers.length * 100 : 0;
    const memoryProgress = data.memory_limit ? memoryUsed / data.memory_limit * 100 : 0;
    renderMetrics(target, `<div class="hero-rings docker-rings">
        ${ring({value:running, label:'RUNNING', detail:`${containers.length} total`, progress:runningProgress})}
        ${ring({value:bytes(memoryUsed), label:'MEMORY', detail:`${memoryProgress.toLocaleString(undefined, {maximumFractionDigits:1})}%`, progress:memoryProgress})}
      </div>
      ${sectionHeading('Projects & containers')}
      <div class="docker-group-list">${dockerGroups.markup(data.groups)}</div>`);
    dockerGroups.restoreFocus(focusKey);
  } catch (error) {
    target.innerHTML = `<div class="utility-placeholder"><strong>Docker unavailable</strong><span>${e(error.message)}</span><a href="/docker">Open Docker →</a></div>`;
  } finally {
    target.append(dockerMessage);
    dockerPanelLoading = false;
  }
}

async function refreshGithubRepositories() {
  const channel = document.querySelector('[data-app-panel="github"]');
  if (!channel || channel.hidden || repositoriesLoading || latest?.demo) return;
  repositoriesLoading = true;
  try {
    const data = await api('/api/github/repositories', {timeout:10000});
    repositoryOperations = new Map(data.repositories.map(repository => [repository.repo.toLowerCase(), repository]));
    const githubData = latest?.services?.github?.data;
    if (githubData && $('#detail').hidden) redrawGithub();
  } catch {
    // The GitHub API panel remains useful when a local checkout is unavailable.
  } finally {
    repositoriesLoading = false;
  }
}

async function controlRepository(button) {
  button.disabled = true;
  try {
    await api(`/api/github/repositories/${encodeURIComponent(button.dataset.id)}/${button.dataset.repositoryAction}`, {method:'POST',timeout:10000});
    setTimeout(refreshGithubRepositories, 300);
  } catch (error) {
    $('#github-message').innerHTML = `<p>${e(error.message)}</p>`;
    button.disabled = false;
  }
}

function render(snapshot) {
  const layout = snapshot.layout || ['codex', 'dagster', 'signoz'];
  const nextSignozHomeMode = ['recent', 'errors'].includes(snapshot.signoz_home_content) ? snapshot.signoz_home_content : 'overview';
  if (nextSignozHomeMode !== signozHomeMode) {
    signozHomeMode = nextSignozHomeMode;
    signozHomeLogs = undefined;
  }
  applyWorkspaceLayout(layout);
  for (const [name, state] of Object.entries(snapshot.services)) {
    if (name === 'codex' && state.data && liveCodexActivity) {
      state.data.tasks = liveCodexActivity.tasks;
      state.data.activity_note = liveCodexActivity.note;
      state.data.integration = liveCodexActivity.integration;
    }
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
    if (name === 'github' && activeWorkspace() === 'github') {
      redrawGithub();
      continue;
    }
    const active = document.activeElement;
    const focusedId = target.contains(active) ? active.dataset.id : null;
    const scrollTop = target.scrollTop;
    renderMetrics(target, state.data
      ? name === 'signoz'
        ? signoz(state.data, signozHomeMode, signozHomeLogs)
        : renderers[name](state.data)
      : state.status === 'loading'
        ? spinner('Loading')
        : empty(state.status === 'disabled' ? 'Not connected' : 'No data') + '<a class="connect-link" href="/settings">Connect ↗</a>');
    target.scrollTop = scrollTop;
    if (focusedId) Array.from(target.querySelectorAll('[data-id]')).find(element => element.dataset.id === focusedId)?.focus({preventScroll: true});
  }
  for (const name of [...new Set([...layout, activeWorkspace()])].filter(name => utilityApps.has(name) && name !== 'docker')) {
    $(`#${name}-content`).innerHTML = utilityPlaceholder(name);
  }
  if (layout.includes('docker') || activeWorkspace() === 'docker') refreshDockerPanel();
  if (layout.includes('github') || activeWorkspace() === 'github') refreshGithubRepositories();
  if (signozHomeVisible()) {
    clearTimeout(signozHomeTimer);
    signozHomeTimer = setTimeout(refreshSignozHome, signozHomeLogs ? 5000 : 0);
  }
}

function updateRefreshIndicators() {
  if (!latest) return;
  const now = latest.server_time + (performance.now() - snapshotReceivedAt) / 1000;
  for (const [name, state] of Object.entries(latest.services)) {
    const indicator = $(`#${name}-refresh`);
    if (!indicator) continue;
    indicator.hidden = ['disabled', 'demo'].includes(state.status);
    if (indicator.hidden) continue;
    const issue = ['stale', 'error'].includes(state.status);
    const remaining = state.next_refresh == null ? 0 : Math.max(0, Math.ceil(state.next_refresh - now));
    const countdown = remaining >= 60 ? `${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, '0')}` : `${remaining}s`;
    const text = !dashboardConnected ? 'Paused' : state.refreshing ? 'Refreshing' : remaining ? `${issue ? 'Retry ' : ''}${countdown}` : 'Due';
    indicator.querySelector('span').textContent = state.refreshing && dashboardConnected ? '' : text;
    indicator.classList.toggle('refreshing', dashboardConnected && Boolean(state.refreshing));
    indicator.classList.toggle('retrying', issue || !dashboardConnected);
    indicator.style.setProperty('--remaining', Math.min(100, remaining / Math.max(1, state.refresh_interval || 1) * 100));
    const age = state.last_success == null ? 'No successful refresh yet' : `Last success ${Math.max(0, Math.floor(now - state.last_success))}s ago`;
    const calendarNote = name === 'github' ? '. Sparklines refresh every minute; saved history updates in the background' : '';
    indicator.title = `${text}. ${age}${calendarNote}`;
    indicator.setAttribute('aria-label', `${name}: ${text}. ${age}${calendarNote}`);
  }
}

async function refresh() {
  try {
    const epoch = layoutEpoch();
    latest = await api('/api/dashboard', {timeout: 8000});
    if (epoch !== layoutEpoch()) latest.layout = currentLayout();
    snapshotReceivedAt = performance.now();
    dashboardConnected = true;
    updateRefreshIndicators();
    $('#connection-warning').hidden = true;
    if ($('#detail').hidden) render(latest);
  } catch {
    dashboardConnected = false;
    updateRefreshIndicators();
    $('#connection-warning').textContent = 'Disconnected · readings paused';
    $('#connection-warning').hidden = false;
  } finally {
    setTimeout(refresh, document.hidden ? 15000 : 5000);
  }
}

async function refreshCodexActivity() {
  try {
    const activity = await api('/api/codex/activity', {timeout:3000});
    liveCodexActivity = activity;
    const signature = JSON.stringify([activity.integration?.connected, activity.tasks.map(task => [task.id, task.timestamp, task.activity_state, task.inferred_active])]);
    const state = latest?.services?.codex;
    if (state?.data && signature !== codexActivitySignature) {
      codexActivitySignature = signature;
      state.data.tasks = activity.tasks;
      state.data.activity_note = activity.note;
      state.data.integration = activity.integration;
      if ($('#detail').hidden && (latest.layout || []).includes('codex')) renderMetrics($('#codex-content'), codex(state.data));
    }
  } catch { /* The normal dashboard status handles unavailable local activity. */ }
  finally { setTimeout(refreshCodexActivity, document.hidden ? 10000 : 500); }
}

async function wakeUpstream() {
  try { await api('/api/refresh', {method:'POST', timeout:3000}); }
  catch { /* The normal dashboard poll reports connection failures. */ }
}

async function openDetail(button) {
  detailTrigger = {service: button.dataset.service, id: button.dataset.id};
  $('#overview').classList.add('detail-open');
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
  const homeLog = event.target.closest('[data-home-log-id]');
  if (homeLog && signozHomeLogs) {
    pendingHomeLog = {data:signozHomeLogs, identifier:homeLog.dataset.homeLogId};
    navigate('signoz');
    return;
  }
  const repositoryButton = event.target.closest('[data-repository-action]');
  if (repositoryButton && !repositoryButton.disabled) {
    controlRepository(repositoryButton);
    return;
  }
  const button = event.target.closest('[data-id][data-service]');
  if (button) openDetail(button);
});

document.addEventListener('workspacechange', () => {
  detailController = null;
  $('#overview').classList.remove('detail-open');
  if (activeWorkspace() === 'signoz' && pendingHomeLog) {
    openHomeLog(pendingHomeLog.data, pendingHomeLog.identifier);
    pendingHomeLog = undefined;
  }
  clearTimeout(signozHomeTimer);
  signozHomeTimer = setTimeout(refreshSignozHome, 0);
  if (latest) render(latest);
});
document.addEventListener('layoutchange', event => {
  if (latest) { latest.layout = event.detail; render(latest); }
  clearTimeout(signozHomeTimer);
  signozHomeTimer = setTimeout(refreshSignozHome, 0);
});

function back() {
  detailController = null;
  $('#detail').hidden = true;
  $('#overview').hidden = false;
  $('#overview').classList.remove('detail-open');
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

let selectedTunnelId = null;
let tunnelPopoverTimer;
let tunnelStatusAvailable = false;
const tunnelNames = {connected:'Connected', connecting:'Connecting', reconnecting:'Reconnecting', disconnected:'Off', error:'Failed'};

function closeTunnelPopover() {
  clearTimeout(tunnelPopoverTimer);
  $('#tunnel-popover').hidden = true;
  document.querySelectorAll('.tunnel-dot').forEach(dot => dot.setAttribute('aria-expanded', 'false'));
  selectedTunnelId = null;
}

function updateTunnelPopover() {
  const dot = [...$('#tunnel-dots').children].find(node => node.dataset.id === selectedTunnelId);
  if (!dot) { closeTunnelPopover(); return; }
  const panel = $('#tunnel-popover');
  const list = $('#tunnel-list');
  const tunnels = tunnelState?.tunnels || [];
  for (const row of [...list.children]) {
    if (!tunnels.some(tunnel => tunnel.id === row.dataset.id)) row.remove();
  }
  for (const tunnel of tunnels) {
    let row = [...list.children].find(node => node.dataset.id === tunnel.id);
    if (!row) {
      row = document.createElement('div');
      row.className = 'tunnel-list-row';
      row.dataset.id = tunnel.id;
      row.innerHTML = '<div><strong></strong><small></small></div><button type="button" class="tunnel-row-toggle" role="switch"><span class="mini-track" aria-hidden="true"><span></span></span></button>';
      list.append(row);
    }
    row.querySelector('strong').textContent = tunnel.name;
    row.querySelector('small').textContent = tunnelStatusAvailable
      ? `${tunnel.ssh_host || 'SSH host unavailable'}${tunnel.message ? ` / ${tunnel.message}` : ''}`
      : 'Status unavailable';
    row.querySelector('small').title = `localhost:${tunnel.local_port} → ${tunnel.remote_host || 'remote'}:${tunnel.remote_port || '?'} via ${tunnel.ssh_host || 'SSH'}`;
    const toggle = row.querySelector('button');
    toggle.dataset.id = tunnel.id;
    toggle.dataset.state = tunnelStatusAvailable ? tunnel.state : 'unknown';
    toggle.setAttribute('aria-busy', String(['connecting', 'reconnecting'].includes(toggle.dataset.state)));
    toggle.setAttribute('aria-checked', String(Boolean(tunnel.desired)));
    toggle.setAttribute('aria-label', `${tunnel.name}: ${tunnelStatusAvailable ? tunnelNames[tunnel.state] || tunnel.state : 'Status unavailable'}`);
    toggle.setAttribute('aria-disabled', String(tunnelLoading || !tunnelStatusAvailable));
  }
  $('#tunnels').setAttribute('aria-disabled', String(tunnelLoading || !tunnelStatusAvailable));
  panel.hidden = false;
  const bounds = $('#tunnel-dots').getBoundingClientRect();
  const beside = bounds.right + panel.offsetWidth + 16 <= innerWidth;
  const below = innerHeight - bounds.bottom - 12;
  const above = bounds.top - 12;
  panel.style.maxHeight = `${beside ? innerHeight - 16 : Math.max(120, below, above)}px`;
  panel.style.left = `${beside ? bounds.right + 8 : Math.max(8, Math.min(bounds.left, innerWidth - panel.offsetWidth - 8))}px`;
  panel.style.top = `${beside ? Math.max(8, Math.min(bounds.top, innerHeight - panel.offsetHeight - 8)) : below >= above ? bounds.bottom + 4 : Math.max(8, bounds.top - panel.offsetHeight - 4)}px`;

}

function openTunnelPopover(dot) {
  clearTimeout(tunnelPopoverTimer);
  document.querySelectorAll('.tunnel-dot').forEach(node => node.setAttribute('aria-expanded', String(node === dot)));
  selectedTunnelId = dot.dataset.id;
  updateTunnelPopover();
}

function renderTunnelDots() {
  const container = $('#tunnel-dots');
  const tunnels = tunnelState?.tunnels || [];
  container.hidden = !tunnels.length;
  for (const dot of [...container.children]) {
    if (!tunnels.some(tunnel => tunnel.id === dot.dataset.id)) dot.remove();
  }
  for (const tunnel of tunnels) {
    let dot = [...container.children].find(node => node.dataset.id === tunnel.id);
    if (!dot) {
      dot = document.createElement('button');
      dot.className = 'tunnel-dot';
      dot.type = 'button';
      dot.dataset.id = tunnel.id;
      dot.setAttribute('aria-haspopup', 'dialog');
      dot.setAttribute('aria-controls', 'tunnel-popover');
      dot.setAttribute('aria-expanded', 'false');
      dot.innerHTML = '<span aria-hidden="true"></span>';
      dot.addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') openTunnelPopover(dot); });
      dot.addEventListener('focus', () => openTunnelPopover(dot));
      dot.addEventListener('click', () => openTunnelPopover(dot));
      dot.addEventListener('pointerleave', () => {
        tunnelPopoverTimer = setTimeout(() => {
          if (!$('#tunnel-popover').matches(':focus-within') && document.activeElement !== dot) closeTunnelPopover();
        }, 200);
      });
      container.append(dot);
    }
    dot.dataset.state = tunnelStatusAvailable ? tunnel.state : 'unknown';
    dot.setAttribute('aria-label', `${tunnel.name}: ${tunnelStatusAvailable ? tunnelNames[tunnel.state] || tunnel.state : 'Status unavailable'}. Tunnel controls`);
  }
  if (selectedTunnelId) updateTunnelPopover();
}

$('#tunnel-popover').addEventListener('pointerenter', () => clearTimeout(tunnelPopoverTimer));
$('#tunnel-popover').addEventListener('pointerleave', () => {
  if (!$('#tunnel-popover').matches(':focus-within')) tunnelPopoverTimer = setTimeout(closeTunnelPopover, 200);
});
document.addEventListener('click', event => {
  if (!event.target.closest('#tunnel-dots, #tunnel-popover')) closeTunnelPopover();
});
document.addEventListener('focusin', event => {
  if (!event.target.closest('#tunnel-dots, #tunnel-popover')) closeTunnelPopover();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && selectedTunnelId) {
    const dot = [...$('#tunnel-dots').children].find(node => node.dataset.id === selectedTunnelId);
    dot?.focus();
    closeTunnelPopover();
  }
  if (event.key === 'Tab' && event.shiftKey && event.target.id === 'tunnels' && selectedTunnelId) {
    event.preventDefault();
    [...$('#tunnel-dots').children].find(node => node.dataset.id === selectedTunnelId)?.focus();
  }
  if (event.key === 'Tab' && !event.shiftKey && event.target.matches('.tunnel-dot') && selectedTunnelId) {
    event.preventDefault();
    $('#tunnels').focus();
  }
});
window.addEventListener('resize', () => { if (selectedTunnelId) updateTunnelPopover(); });
$('#tunnel-list').addEventListener('click', async event => {
  const toggle = event.target.closest('.tunnel-row-toggle');
  if (!toggle) return;
  const tunnel = tunnelState?.tunnels?.find(row => row.id === toggle.dataset.id);
  if (!tunnel || tunnelLoading || !tunnelStatusAvailable) return;
  tunnelLoading = true;
  tunnelMutation += 1;
  updateTunnelPopover();
  toggle.dataset.state = 'connecting';
  try {
    const action = tunnel.desired ? 'disconnect' : 'connect';
    showTunnelStatus(await api(`/api/tunnels/${encodeURIComponent(tunnel.id)}/${action}`, {method:'POST', timeout:15000}));
  } catch (error) {
    $('#tunnel-warning').textContent = error.message;
    $('#tunnel-warning').hidden = false;
  } finally {
    tunnelLoading = false;
    if (selectedTunnelId) updateTunnelPopover();
  }
});

function showTunnelStatus(data) {
  tunnelState = data;
  tunnelStatusAvailable = true;
  renderTunnelDots();
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
  const connecting = data.tunnels?.some(tunnel => ['connecting', 'reconnecting'].includes(tunnel.state));
  button.dataset.state = connecting ? 'connecting' : data.state;
  button.setAttribute('aria-busy', String(Boolean(connecting)));
  button.setAttribute('aria-checked', String(Boolean(count && data.tunnels.every(tunnel => tunnel.desired))));
  button.setAttribute('aria-label', connecting ? 'SSH tunnels connecting. Disconnect all SSH tunnels' : label);
  const problem = data.tunnels?.find(tunnel => tunnel.message)?.message;
  $('#tunnel-warning').hidden = !problem;
  $('#tunnel-warning').textContent = problem ? `SSH · ${problem}` : '';
}

async function refreshTunnels() {
  try {
    if (tunnelLoading) return;
    const mutation = tunnelMutation;
    const data = await api('/api/tunnels', {timeout:5000});
    if (!tunnelLoading && mutation === tunnelMutation) showTunnelStatus(data);
  } catch {
    tunnelStatusAvailable = false;
    renderTunnelDots();
    $('#tunnels').dataset.state = 'error';
    $('#tunnel-warning').textContent = 'Could not read SSH tunnel status';
    $('#tunnel-warning').hidden = false;
  } finally {
    setTimeout(refreshTunnels, document.hidden ? 15000 : 5000);
  }
}

$('#tunnels').addEventListener('click', async () => {
  if (tunnelLoading || !tunnelStatusAvailable) return;
  if (!tunnelState || tunnelState.state === 'unconfigured') {
    window.location.assign('/settings#ssh-tunnels');
    return;
  }
  tunnelLoading = true;
  tunnelMutation += 1;
  $('#tunnels').dataset.state = 'connecting';
  if (selectedTunnelId) updateTunnelPopover();
  try {
    const allOn = tunnelState.tunnels.length && tunnelState.tunnels.every(tunnel => tunnel.desired);
    const action = allOn ? 'disconnect' : 'connect';
    showTunnelStatus(await api(`/api/tunnels/${action}`, {method:'POST', timeout:15000}));
  } catch (error) {
    $('#tunnels').dataset.state = 'error';
    $('#tunnels').setAttribute('aria-label', error.message);
    $('#tunnel-warning').textContent = error.message;
    $('#tunnel-warning').hidden = false;
  } finally {
    tunnelLoading = false;
    if (selectedTunnelId) updateTunnelPopover();
  }
});

function clock() {
  const now = new Date();
  const parts = now.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false}).split(':');
  $('#clock').innerHTML = `${parts[0]}<span class="clock-colon">:</span>${parts[1]}`;
  $('#clock').dateTime = now.toISOString();
  $('#date').textContent = now.toLocaleDateString([], {weekday: 'short', day: '2-digit', month: 'short'});
}

$('#overview').append($('#detail'));
clock();
setInterval(clock, 1000);
setInterval(updateRefreshIndicators, 1000);
await wakeUpstream();
refresh();
refreshTunnels();
refreshCodexActivity();
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) wakeUpstream();
});
setInterval(() => {
  if (!document.hidden) refreshGithubRepositories();
}, 5000);
