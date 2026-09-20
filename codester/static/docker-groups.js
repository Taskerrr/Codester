import {api, escape as e} from './common.js';

const icons = {
  start:'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5a1 1 0 0 1 1.5-.86l12 7.5a1 1 0 0 1 0 1.72l-12 7.5A1 1 0 0 1 7 19.5Z"/></svg>',
  stop:'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="5" y="4" width="5" height="16" rx="1"/><rect x="14" y="4" width="5" height="16" rx="1"/></svg>',
};

function compactStatus(row) {
  const units = {second:'s', minute:'m', hour:'h', day:'d', week:'w', month:'mo', year:'y'};
  return String(row.status || row.state || 'Unknown')
    .replace(/^Up\s+/i, '')
    .replace(/^Exited\s*\(([^)]+)\)\s*/i, 'Exit $1 · ')
    .replace(/\bless than a second\b/gi, '<1s')
    .replace(/\babout\s+/gi, '~')
    .replace(/\b(\d+|an?|one)\s+(second|minute|hour|day|week|month|year)s?\b/gi, (_, amount, unit) => `${/^\d+$/.test(amount) ? amount : 1}${units[unit.toLowerCase()]}`)
    .replace(/\s+ago\b/gi, '')
    .replace(/\s*\(healthy\)/gi, '')
    .replace(/\s*\(unhealthy\)/gi, ' · unhealthy')
    .replace(/\s*\(health: starting\)/gi, ' · starting')
    .replace(/\s*·\s*$/, '')
    .trim();
}

export class DockerGroups {
  constructor(root, report, refresh) {
    this.root = root;
    this.report = report;
    this.refresh = refresh;
    this.expanded = new Set();
    this.groups = new Map();
    this.pending = '';
    this.busy = false;
    root.addEventListener('click', event => this.click(event));
    root.addEventListener('keydown', event => {
      if (event.key === 'Escape' && this.pending) { event.preventDefault(); this.clearConfirmation(); }
    });
  }
  get paused() { return this.busy || Boolean(this.pending); }
  key(group) { return `${group.kind}:${group.id}`; }
  markup(groups) {
    this.groups = new Map(groups.map(group => [this.key(group), group]));
    return groups.map(group => {
      const key = this.key(group);
      const project = group.kind === 'project';
      const expanded = this.expanded.has(key);
      const status = project ? `${group.running}/${group.total}` : compactStatus(group.containers[0]);
      const statusLabel = project ? `${group.running} of ${group.total} containers running` : group.containers[0].status || group.containers[0].state;
      const protectedNote = !group.manageable ? 'Includes Codester; manage outside this dashboard.' : group.total > 50 ? 'Manage projects larger than 50 containers in Docker Desktop.' : '';
      const heading = `<strong title="${e(group.name)}">${e(group.name)}</strong><small class="${project ? 'docker-count-pill' : 'docker-uptime'}" data-state="${e(group.state)}" title="${e(statusLabel)}" aria-label="${e(statusLabel)}">${e(status)}</small>`;
      const actions = [];
      if (group.running < group.total) actions.push('start');
      if (group.active) actions.push('stop');
      return `<section class="docker-group" data-docker-group="${e(key)}">
        <div class="docker-group-heading">
          ${project ? `<button type="button" class="docker-project-toggle" data-docker-toggle="${e(key)}" data-docker-key="toggle:${e(key)}" aria-expanded="${expanded}" aria-controls="docker-members-${e(group.id)}"><span class="docker-chevron" aria-hidden="true">›</span><span class="docker-name-line">${heading}</span></button>` : `<div class="docker-standalone-name docker-name-line">${heading}</div>`}
          <div class="docker-group-actions">${actions.map(action => {
            const verb = action === 'start' ? 'Start' : 'Stop';
            const label = project ? `${verb} all containers in ${group.name}` : `${verb} ${group.name}`;
            return `<button type="button" class="docker-group-action ${action}" data-docker-action="${action}" data-docker-target="${e(key)}" data-docker-key="${action}:${e(key)}" aria-label="${e(label)}" title="${e(protectedNote || label)}" ${protectedNote ? 'disabled' : ''}>${icons[action]}</button>`;
          }).join('')}</div>
        </div>
        <p class="docker-group-confirmation" role="status" hidden></p>
        ${protectedNote ? `<p class="docker-group-note">${e(protectedNote)}</p>` : ''}
        ${project ? `<ul id="docker-members-${e(group.id)}" class="docker-members" ${expanded ? '' : 'hidden'}>${group.containers.map(row => `<li><div><strong>${e(row.service || row.name)}</strong><small>${e(row.name)} · ${e(row.image)}</small></div><span data-state="${row.running ? 'running' : 'stopped'}" title="${e(row.status || row.state)}" aria-label="${e(row.status || row.state)}">${e(compactStatus(row))}</span></li>`).join('')}</ul>` : ''}
      </section>`;
    }).join('') || '<p class="docker-groups-empty">No containers</p>';
  }
  restoreFocus(key) {
    if (!key) return;
    const controls = [...this.root.querySelectorAll('[data-docker-key]')];
    const opposite = key.replace(/^(start|stop):/, match => match === 'start:' ? 'stop:' : 'start:');
    const target = controls.find(node => node.dataset.dockerKey === key)
      || controls.find(node => node.dataset.dockerKey === opposite)
      || controls.find(node => node.dataset.dockerKey === key.replace(/^(start|stop):/, 'toggle:'));
    target?.focus({preventScroll:true});
  }
  clearConfirmation() {
    this.pending = '';
    clearTimeout(this.timer);
    for (const note of this.root.querySelectorAll('.docker-group-confirmation')) note.hidden = true;
    for (const button of this.root.querySelectorAll('.docker-group-action.confirm')) {
      button.classList.remove('confirm');
      button.setAttribute('aria-label', button.dataset.originalLabel);
    }
  }
  async click(event) {
    const toggle = event.target.closest('[data-docker-toggle]');
    if (toggle) {
      const key = toggle.dataset.dockerToggle;
      const expanded = !this.expanded.has(key);
      if (expanded) this.expanded.add(key); else this.expanded.delete(key);
      toggle.setAttribute('aria-expanded', String(expanded));
      document.getElementById(toggle.getAttribute('aria-controls')).hidden = !expanded;
      return;
    }
    const button = event.target.closest('[data-docker-target]');
    if (!button || button.disabled || this.busy) return;
    const key = button.dataset.dockerTarget;
    const action = button.dataset.dockerAction;
    const group = this.groups.get(key);
    if (!group?.manageable) return;
    if (action === 'stop' && this.pending !== key) {
      this.clearConfirmation();
      this.pending = key;
      button.dataset.originalLabel = button.getAttribute('aria-label');
      button.setAttribute('aria-label', `Confirm: ${button.dataset.originalLabel}`);
      button.classList.add('confirm');
      const note = button.closest('.docker-group').querySelector('.docker-group-confirmation');
      note.textContent = group.kind === 'project' ? `Stop all in ${group.name}? Tap pause again.` : `Stop ${group.name}? Tap pause again.`;
      note.hidden = false;
      this.timer = setTimeout(() => this.clearConfirmation(), 5000);
      return;
    }
    this.clearConfirmation();
    this.busy = true;
    for (const control of this.root.querySelectorAll('[data-docker-target]')) control.disabled = true;
    button.classList.add('working');
    this.report(`${action === 'start' ? 'Starting' : 'Stopping'} ${group.name}…`, false);
    try {
      const path = group.kind === 'project' ? 'projects' : 'containers';
      const response = await api(`/api/docker/${path}/${encodeURIComponent(group.id)}/${action}`, {method:'POST', body:JSON.stringify({container_ids:group.containers.map(row => row.id)}), timeout:120000});
      this.report(response.message || `${group.name}: ${action} requested.`, response.ok === false);
    } catch (error) { this.report(error.message, true); }
    finally {
      this.busy = false;
      await this.refresh();
      this.restoreFocus(`${action}:${key}`);
    }
  }
}
