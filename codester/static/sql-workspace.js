import {$, api, escape as e} from './common.js';
import './postgres.js';

export function initSQLWorkspace() {
  let connections = [];
  let demo = true;
  let loading = false;
  let running = false;
  let requestId;
  let editingId;
  let cancelling = false;
  let startedAt = 0;
  let timer;
  let currentId = '';
  let currentRevision = '';
  const drafts = new Map();
  const selected = () => connections.find(row => row.id === currentId);
  const form = $('#sql-connection-form');
  const workspace = $('#sql-workspace');

  function remember() {
    if (currentId) drafts.set(currentId, {revision:currentRevision, query:$('#sql-query').value, results:$('#sql-results').innerHTML, status:$('#sql-result-status').textContent, elapsed:$('#sql-elapsed').textContent, error:$('#sql-result-status').classList.contains('error')});
  }
  function resizeQuery() {
    const query = $('#sql-query');
    if (!query.clientWidth) return;
    query.style.height = 'auto';
    query.style.height = Math.min(query.scrollHeight + 2, 240) + 'px';
  }
  function controls() {
    const button = $('#sql-run');
    button.disabled = running ? cancelling : demo || !selected() || !$('#sql-query').value.trim();
    $('#sql-connection').disabled = running;
    $('#sql-query').readOnly = running;
    button.classList.toggle('is-running', running);
    button.setAttribute('aria-label', running ? 'Cancel query' : 'Run query');
    button.title = running ? 'Cancel query' : 'Run query (Ctrl/⌘ Enter)';
    button.innerHTML = running
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4l14 8-14 8z"/></svg>';
  }
  function selectConnection(id) {
    remember();
    currentId = id;
    $('#sql-connection').value = id;
    const connection = selected();
    const saved = drafts.get(id);
    const retainResults = saved && saved.revision === connection?.revision;
    currentRevision = connection?.revision || '';
    $('#sql-query').value = saved?.query || '';
    $('#sql-results').innerHTML = retainResults ? saved.results : '';
    $('#sql-result-status').textContent = retainResults ? saved.status : saved ? 'Connection changed. Run the query to refresh results.' : '';
    $('#sql-result-status').classList.toggle('error', retainResults && saved.error);
    $('#sql-connection').title = connection ? `${connection.host}:${connection.port} / ${connection.database} · ${connection.username}` : 'New connection';
    $('#sql-elapsed').textContent = retainResults ? saved.elapsed || '' : '';
    resizeQuery();
    workspace.dataset.connection = id;
    controls();
    document.dispatchEvent(new Event('sqlconnectionchange'));
  }
  function renderConnections(preferred = currentId) {
    preferred = connections.some(row => row.id === preferred) ? preferred : connections[0]?.id || '';
    $('#sql-connection').innerHTML = (connections.length ? connections.map(row => `<option value="${e(row.id)}">${e(row.name)} · ${e(row.environment)} · ${e(row.database)}</option>`).join('') : '<option value="" disabled>New connection</option>') + '<option value="__new">New connection…</option>' + (connections.some(row => row.id === preferred && row.id !== 'monitor') ? '<option value="__edit">Edit connection…</option>' : '');
    $('#sql-notice').textContent = demo ? 'Demo mode is on. Turn it off in Settings to run SQL against a saved connection.' : '';
    selectConnection(connections.some(row => row.id === preferred) ? preferred : connections[0]?.id || '');
  }
  async function loadConnections() {
    if (loading || running) return;
    loading = true;
    try {
      const response = await api('/api/sql/connections');
      connections = response.connections; demo = response.demo;
      renderConnections();
    } catch (error) { $('#sql-notice').textContent = error.message; }
    finally { loading = false; }
  }
  function editConnection(connection) {
    form.reset();
    editingId = connection?.id || crypto.randomUUID();
    for (const field of ['name','environment','host','port','database','username','sslmode','sslrootcert']) {
      if (connection) form.elements.namedItem(field).value = connection[field];
    }
    $('#sql-connection-title').textContent = connection ? `Edit ${connection.name}` : 'New connection';
    $('#sql-delete-connection').hidden = !connection;
    $('#sql-delete-connection').textContent = 'Delete connection';
    $('#sql-connection-error').textContent = '';
    form.hidden = false;
    workspace.classList.add('connection-editing');
    form.elements.namedItem('name').focus();
  }
  function closeForm() {
    form.hidden = true; workspace.classList.remove('connection-editing');
    form.elements.namedItem('password').value = '';
    $('#sql-connection').focus();
  }
  $('#sql-close-connection').addEventListener('click', closeForm);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    data.port = Number(data.port); data.clear_password = form.elements.namedItem('clear_password').checked;
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    try {
      const response = await api(`/api/sql/connections/${editingId}`, {method:'PUT', body:JSON.stringify(data)});
      connections = response.connections;
      closeForm(); renderConnections(editingId);
    } catch (error) { $('#sql-connection-error').textContent = error.message; }
    finally { for (const button of form.querySelectorAll('button')) button.disabled = false; }
  });
  $('#sql-delete-connection').addEventListener('click', async () => {
    const button = $('#sql-delete-connection');
    if (button.textContent === 'Delete connection') { button.textContent = 'Confirm deletion'; $('#sql-connection-error').textContent = 'Delete this saved connection and its password? The database is not changed.'; return; }
    for (const action of form.querySelectorAll('button')) action.disabled = true;
    try {
      await api(`/api/sql/connections/${editingId}`, {method:'DELETE'});
      closeForm(); connections = connections.filter(row => row.id !== editingId); renderConnections();
    } catch (error) { $('#sql-connection-error').textContent = error.message; }
    finally { for (const action of form.querySelectorAll('button')) action.disabled = false; }
  });
  $('#sql-connection').addEventListener('change', event => {
    const value = event.target.value;
    if (value === '__new' || value === '__edit') {
      event.target.value = currentId;
      editConnection(value === '__edit' ? selected() : undefined);
    } else { closeForm(); renderConnections(value); }
  });
  $('#sql-query').addEventListener('input', () => { resizeQuery(); controls(); });
  new ResizeObserver(resizeQuery).observe($('#sql-editor-view'));
  function resultTable(result) {
    if (!result.columns.length) return `<p class="sql-empty">${e(result.status || 'Statement completed')}${result.affected_rows !== null ? ` · ${e(result.affected_rows)} rows affected` : ''}.</p>`;
    return `<table><caption>Query results</caption><thead><tr>${result.columns.map(name => `<th scope="col">${e(name)}</th>`).join('')}</tr></thead><tbody>${result.rows.map(row => `<tr>${row.map(value => `<td${value === null ? ' class="sql-null"' : ''}>${value === null ? 'NULL' : e(value)}</td>`).join('')}</tr>`).join('')}</tbody></table>${!result.rows.length ? `<p class="sql-empty">${result.truncated ? 'No rows fit within the preview limit. Select fewer or smaller columns.' : 'Query completed with no rows.'}</p>` : ''}`;
  }
  async function run() {
    if (running || demo || !selected() || !$('#sql-query').value.trim()) return;
    const connection = selected();
    const query = $('#sql-query').value;
    const mode = 'write';
    const confirmed = true;
    running = true; cancelling = false; requestId = crypto.randomUUID(); controls();
    startedAt = performance.now();
    const updateElapsed = () => { $('#sql-elapsed').textContent = ((performance.now() - startedAt) / 1000).toFixed(1) + 's'; };
    updateElapsed(); timer = setInterval(updateElapsed, 100);
    const status = $('#sql-result-status');
    status.classList.remove('error'); status.textContent = '';
    $('#sql-results').innerHTML = '';
    $('#sql-results').setAttribute('aria-busy', 'true');
    try {
      const result = await api('/api/sql/run', {method:'POST', body:JSON.stringify({connection_id:currentId, revision:connection.revision, query, mode, confirmed, request_id:requestId}), timeout:45000});
      $('#sql-results').innerHTML = resultTable(result);
      $('#sql-elapsed').textContent = (result.elapsed_ms / 1000).toFixed(1) + 's';
      status.textContent = `${result.rows.length} rows${result.truncated ? ' · Preview truncated (500 rows / 4,000 characters per cell / 2 MB)' : ''}`;
    } catch (error) {
      status.classList.add('error'); status.textContent = `${connection.name}: ${error.message}`;
      $('#sql-results').innerHTML = `<p class="sql-empty">No results available.${mode === 'write' ? ' For a failed or interrupted write, verify the database state before retrying.' : ''}</p>`;
    } finally { clearInterval(timer); running = false; requestId = null; $('#sql-results').setAttribute('aria-busy', 'false'); controls(); remember(); }
  }
  $('#sql-run').addEventListener('click', () => running ? cancel() : run());
  $('#sql-query').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); run(); }
  });
  async function cancel() {
    if (!requestId) return;
    const cancelledId = requestId;
    cancelling = true; controls();
    try {
      const response = await api(`/api/sql/cancel/${cancelledId}`, {method:'POST', timeout:8000});
      if (requestId === cancelledId) $('#sql-result-status').textContent = response.cancelled ? 'Cancellation requested. Waiting for the database…' : 'Query has already finished. Waiting for its result…';
    } catch (error) { if (requestId === cancelledId) { $('#sql-result-status').textContent = error.message; cancelling = false; controls(); } }
  }
  for (const tab of ['editor','activity']) $(`#sql-tab-${tab}`).addEventListener('click', () => {
    $('#sql-editor-view').hidden = tab !== 'editor';
    $('#sql-activity-view').hidden = tab !== 'activity';
    for (const name of ['editor','activity']) $(`#sql-tab-${name}`).setAttribute('aria-pressed', String(name === tab));
    document.dispatchEvent(new Event('sqlactivitychange'));
  });
  document.addEventListener('workspacechange', event => {
    if (event.detail === 'postgres') loadConnections();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !workspace.hidden) loadConnections(); });
  controls();
}
