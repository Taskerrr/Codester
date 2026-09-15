export const $ = (selector) => document.querySelector(selector);
export function codexTrustNotice(integration) {
  if (integration?.connected !== false) return '';
  return '<div class="codex-trust-notice" role="status"><strong>Finish connecting Codex</strong><p>Go to Codex Settings → Hooks → trust all Codester hooks.</p><small>Then send a message in Codex to verify the connection.</small></div>';
}
export const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export async function api(path, options = {}) {
  const {timeout = 90000, ...fetchOptions} = options;
  const response = await fetch(path, {...fetchOptions, headers: {'Content-Type': 'application/json', 'X-Codester-CSRF': $('meta[name="csrf-token"]').content, ...options.headers}, signal: AbortSignal.timeout(timeout)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed. Try again.');
  return data;
}
export function duration(seconds) {
  if (seconds == null || !Number.isFinite(Number(seconds))) return 'Unavailable';
  const minutes = Math.max(0, Math.floor(seconds / 60));
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return minutes ? `${minutes}m` : '<1m';
}
export function epoch(value) {
  if (value == null) return null;
  if (typeof value === 'string' && !/^\d+(\.\d+)?$/.test(value)) return Date.parse(value) / 1000;
  let number = Number(value);
  if (number > 1e17) number /= 1e9;
  else if (number > 1e14) number /= 1e6;
  else if (number > 1e11) number /= 1e3;
  return Number.isFinite(number) ? number : null;
}
export function ago(value) { const stamp = epoch(value); return stamp == null ? 'Time unavailable' : `${duration(Date.now()/1000 - stamp)} ago`; }
export function compactTime(value) {
  const stamp = epoch(value);
  if (stamp == null) return '—';
  const date = new Date(stamp * 1000);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', hour12:false});
  const day = String(date.getDate()).padStart(2, '0');
  return `${day} ${date.toLocaleString([], {month:'short'})}`;
}
