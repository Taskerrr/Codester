import {$, api, escape as e} from './common.js';

// Poll only saved execution state; reads never open an SSH session.
export class GitHubUpdates {
  constructor(redraw, visible) {
    this.redraw = redraw;
    this.visible = visible;
    this.rows = [];
    this.demo = true;
    this.loading = false;
    this.stale = false;
    this.version = 0;
    this.pending = new Set();
    this.expanded = new Set();
    this.confirmations = new Map();
    this.errors = new Map();
    document.addEventListener('click', event => {
      const button = event.target.closest('[data-github-update]');
      if (!button || button.disabled) return;
      const id = button.dataset.id;
      const row = this.rows.find(item => item.id === id);
      if (!row) return;
      const action = button.dataset.githubUpdate;
      if (action === 'output') {
        if (this.expanded.has(id)) this.expanded.delete(id); else this.expanded.add(id);
        this.redraw();
      } else if (action === 'back') {
        this.confirmations.delete(id); this.redraw();
      } else if (action === 'confirm') {
        const revision = this.confirmations.get(id);
        if (revision) this.run(row, revision, true);
      } else if (row.confirm) {
        this.confirmations.set(id, row.revision); this.redraw();
      } else this.run(row, row.revision);
    });
    document.addEventListener('workspacechange', () => this.refresh());
    setInterval(() => { if (!document.hidden && this.visible()) this.refresh(); }, 2000);
    setInterval(() => {
      for (const node of document.querySelectorAll('[data-update-start]')) node.textContent = this.elapsed(Number(node.dataset.updateStart));
    }, 1000);
  }
  elapsed(start, finish = Date.now() / 1000) {
    return `${Math.max(0, Math.floor(finish - start))}s`;
  }
  async refresh() {
    if (this.loading || !this.visible() || this.pending.size) return;
    this.loading = true;
    const version = this.version;
    try {
      const data = await api('/api/github/updates', {timeout:8000});
      if (version !== this.version) return;
      this.rows = data.repositories; this.demo = data.demo; this.stale = false;
      for (const row of this.rows) {
        if (this.confirmations.has(row.id) && this.confirmations.get(row.id) !== row.revision) {
          this.confirmations.delete(row.id);
          this.errors.set(row.id, 'Update settings changed. Review the target and try again.');
        }
      }
    } catch { if (version === this.version) this.stale = true; }
    finally { this.loading = false; this.redraw(); }
  }
  async run(row, revision, confirmed = false) {
    if (this.pending.has(row.id) || row.action?.state === 'running' || this.demo || this.stale) return;
    this.version += 1;
    this.pending.add(row.id); this.errors.delete(row.id); this.confirmations.delete(row.id); this.redraw();
    try {
      const action = await api(`/api/github/updates/${encodeURIComponent(row.id)}`, {method:'POST',body:JSON.stringify({revision,confirmed}),timeout:10000});
      const current = this.rows.find(item => item.id === row.id);
      if (current) current.action = action;
    } catch (error) { this.errors.set(row.id, error.message); }
    finally { this.pending.delete(row.id); this.redraw(); this.refresh(); }
  }
  row(name) { return this.rows.find(row => row.repo.toLowerCase() === name.toLowerCase()); }
  controls(name) {
    const row = this.row(name);
    if (!row) return '';
    const action = row.action;
    const running = action?.state === 'running';
    const pending = this.pending.has(row.id);
    const disabled = this.demo || this.stale || !row.configured || running || pending;
    const title = this.demo ? 'Updates unavailable in demo mode' : this.stale ? 'Update status unavailable' : !row.configured ? 'Configure a remote update in Settings → GitHub' : `${row.target} / ${row.path}`;
    const status = action ? `<button type="button" class="repo-update-status" data-state="${e(action.state)}" data-github-update="output" data-id="${e(row.id)}" aria-expanded="${this.expanded.has(row.id)}" aria-label="Show update output for ${e(name)}">${running ? `<span data-update-start="${action.started_at}">${this.elapsed(action.started_at)}</span>` : ({success:'Finished',error:'Failed',unknown:'Unknown'}[action.state] || '')}</button>` : '';
    return `<button type="button" class="repo-update-button" data-github-update="run" data-id="${e(row.id)}" ${disabled ? 'disabled' : ''} title="${e(title)}" aria-label="Update ${e(name)}">${running || pending ? 'Updating…' : 'Update'}</button>${status}`;
  }
  detail(name) {
    const row = this.row(name);
    if (!row) return '';
    const id = e(row.id);
    const confirmation = this.confirmations.has(row.id) ? `<div class="repo-update-confirm"><p>Update ${e(name)} on ${e(row.target)} / ${e(row.path)}?</p><pre>${e(row.script)}</pre><button type="button" class="quiet-button" data-github-update="confirm" data-id="${id}">Confirm update</button><button type="button" class="quiet-button" data-github-update="back" data-id="${id}">Back</button></div>` : '';
    const action = row.action;
    const output = this.expanded.has(row.id) && action ? `<div class="repo-update-output"><p>${e(action.host)} / ${e(action.path)} · ${e(new Date(action.started_at * 1000).toLocaleString())}</p><pre>${e(action.script)}</pre><pre class="repo-update-log" tabindex="0" aria-label="Update output for ${e(name)}">${e(action.output || (action.state === 'running' ? 'Waiting for output…' : 'No output.'))}</pre><p>${e(action.message)}${action.truncated ? ' Showing the last 64 KB.' : ''}</p></div>` : '';
    const error = this.errors.get(row.id);
    return confirmation + output + (error ? `<p class="repo-update-error" role="alert">${e(error)}</p>` : '');
  }
}
