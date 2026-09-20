import {$, api, escape as e} from './common.js';
import './postgres.js';

export function initSQLWorkspace() {
  let connections = [];
  let demo = true;
  let loading = false;
  let running = false;
  let requestId;
  let editingId;
  let pending;
  let currentId = '';
  let currentRevision = '';
  const drafts = new Map();
  const selected = () => connections.find(row => row.id === currentId);
  const form = $('#sql-connection-form');
  const workspace = $('#sql-workspace');

  function remember() {
    if (currentId) drafts.set(currentId, {revision:currentRevision, query:$('#sql-query').value, results:$('#sql-results').innerHTML, status:$('#sql-result-status').textContent, error:$('#sql-result-status').classList.contains('error')});
  }
  function clearConfirmation() { pending = null; $('#sql-write-confirmation').hidden = true; }
  function controls() {
    $('#sql-run').disabled = running || demo || !selected() || !$('#sql-query').value.trim();
    $('#sql-cancel').disabled = !running;
    for (const id of ['sql-connection','sql-mode','sql-add-connection','sql-edit-connection']) $(`#${id}`).disabled = running;
    $('#sql-edit-connection').disabled ||= !selected() || currentId === 'monitor';
    $('#sql-query').readOnly = running;
    $('#sql-run').textContent = running ? 'Running…' : 'Run query';
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
    $('#sql-results').innerHTML = retainResults ? saved.results : '<p class="sql-empty">Your results will appear here.</p>';
    $('#sql-result-status').textContent = retainResults ? saved.status : saved ? 'Connection changed. Run the query to refresh results.' : 'Run a query to see results.';
    $('#sql-result-status').classList.toggle('error', retainResults && saved.error);
    $('#sql-mode').value = 'read';
    $('#sql-environment').textContent = connection?.environment || 'No connection';
    $('#sql-environment').dataset.environment = connection?.environment || '';
    $('#sql-target').textContent = connection ? `${connection.name} · ${connection.host}:${connection.port} / ${connection.database} · ${connection.username}` : 'Add a named PostgreSQL connection to get started.';
    workspace.dataset.connection = id;
    clearConfirmation();
    controls();
    document.dispatchEvent(new Event('sqlconnectionchange'));
  }
  function renderConnections(preferred = currentId) {
    $('#sql-connection').innerHTML = connections.length ? connections.map(row => `<option value="${e(row.id)}">${e(row.name)}</option>`).join('') : '<option value="">No saved connections</option>';
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
    clearConfirmation();
  }
  function closeForm() {
    form.hidden = true; workspace.classList.remove('connection-editing');
    form.elements.namedItem('password').value = '';
    $('#sql-add-connection').focus();
  }
  $('#sql-add-connection').addEventListener('click', () => editConnection());
  $('#sql-edit-connection').addEventListener('click', () => editConnection(selected()));
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
  $('#sql-connection').addEventListener('change', event => selectConnection(event.target.value));
  $('#sql-query').addEventListener('input', () => { clearConfirmation(); controls(); });
  $('#sql-mode').addEventListener('change', clearConfirmation);
  function resultTable(result) {
    if (!result.columns.length) return `<p class="sql-empty">${e(result.status || 'Statement completed')}${result.affected_rows !== null ? ` · ${e(result.affected_rows)} rows affected` : ''}.</p>`;
    return `<table><caption>Query results</caption><thead><tr>${result.columns.map(name => `<th scope="col">${e(name)}</th>`).join('')}</tr></thead><tbody>${result.rows.map(row => `<tr>${row.map(value => `<td${value === null ? ' class="sql-null"' : ''}>${value === null ? 'NULL' : e(value)}</td>`).join('')}</tr>`).join('')}</tbody></table>${!result.rows.length ? `<p class="sql-empty">${result.truncated ? 'No rows fit within the preview limit. Select fewer or smaller columns.' : 'Query completed with no rows.'}</p>` : ''}`;
  }
  async function run(confirmed = false) {
    if (running || demo || !selected() || !$('#sql-query').value.trim()) return;
    const connection = selected();
    const query = $('#sql-query').value;
    const mode = $('#sql-mode').value;
    if (mode === 'write' && !confirmed) {
      pending = {id:currentId, query, revision:connection.revision};
      $('#sql-write-description').textContent = `Run in write mode on ${connection.name} (${connection.environment}), ${connection.host}:${connection.port}/${connection.database}? Changes are committed immediately.`;
      $('#sql-write-confirmation').hidden = false;
      $('#sql-confirm-run').focus();
      return;
    }
    if (mode === 'write' && (!pending || pending.id !== currentId || pending.query !== query || pending.revision !== connection.revision)) { clearConfirmation(); return; }
    clearConfirmation(); running = true; requestId = crypto.randomUUID(); controls();
    const status = $('#sql-result-status');
    status.classList.remove('error'); status.textContent = `Running on ${connection.name}…`;
    $('#sql-results').innerHTML = '<p class="sql-empty">Waiting for results…</p>';
    try {
      const result = await api('/api/sql/run', {method:'POST', body:JSON.stringify({connection_id:currentId, revision:connection.revision, query, mode, confirmed, request_id:requestId}), timeout:45000});
      $('#sql-results').innerHTML = resultTable(result);
      status.textContent = `${result.connection_name} · ${result.environment} · ${result.rows.length} of ${result.row_count} result rows · ${result.elapsed_ms} ms${result.truncated ? ' · Preview truncated (500 rows / 4,000 characters per cell / 2 MB)' : ''}`;
    } catch (error) {
      status.classList.add('error'); status.textContent = `${connection.name}: ${error.message}`;
      $('#sql-results').innerHTML = `<p class="sql-empty">No results available.${mode === 'write' ? ' For a failed or interrupted write, verify the database state before retrying.' : ''}</p>`;
    } finally { running = false; requestId = null; controls(); remember(); }
  }
  $('#sql-run').addEventListener('click', () => run());
  $('#sql-confirm-run').addEventListener('click', () => run(true));
  $('#sql-dismiss-confirmation').addEventListener('click', () => { clearConfirmation(); $('#sql-run').focus(); });
  $('#sql-query').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); run(); }
  });
  $('#sql-cancel').addEventListener('click', async () => {
    if (!requestId) return;
    const cancelling = requestId;
    $('#sql-cancel').disabled = true;
    try {
      const response = await api(`/api/sql/cancel/${cancelling}`, {method:'POST', timeout:8000});
      if (requestId === cancelling) $('#sql-result-status').textContent = response.cancelled ? 'Cancellation requested. Waiting for the database…' : 'Query has already finished. Waiting for its result…';
    } catch (error) { if (requestId === cancelling) { $('#sql-result-status').textContent = error.message; $('#sql-cancel').disabled = false; } }
  });
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
