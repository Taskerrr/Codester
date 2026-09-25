import {$, api, escape as e} from './common.js';

const paths = {
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon:'<path d="M19.5 15.5A8 8 0 0 1 8.5 4.5a8 8 0 1 0 11 11Z"/>',
  cloud:'<path d="M6 18h12a4 4 0 0 0 0-8 6 6 0 0 0-11.6-1.8A5 5 0 0 0 6 18Z"/>',
  rain:'<path d="M6 15h12a3 3 0 0 0 0-6 5 5 0 0 0-9.6-1.8A4 4 0 0 0 6 15ZM8 18l-1 3m6-3-1 3m6-3-1 3"/>',
  snow:'<path d="M12 3v18M4 7l16 10M4 17 20 7M9 5l3 3 3-3M9 19l3-3 3 3"/>',
  fog:'<path d="M4 8h16M2 12h20M4 16h16M7 20h10"/>',
  thunder:'<path d="M5 13a4 4 0 0 1 1-8 6 6 0 0 1 11 1 4 4 0 0 1 2 7M12 10l-4 7h5l-2 5 7-9h-6Z"/>',
  unknown:'<circle cx="12" cy="12" r="8"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3v.2"/>',
};
function condition(symbol = '') {
  if (symbol.includes('thunder')) return ['thunder','Thunderstorms'];
  if (symbol.includes('sleet')) return ['snow','Sleet'];
  if (symbol.includes('snow')) return ['snow','Snow'];
  if (symbol.includes('rain')) return ['rain',symbol.includes('heavy') ? 'Heavy rain' : symbol.includes('showers') ? 'Showers' : 'Rain'];
  if (symbol.includes('fog')) return ['fog','Fog'];
  if (symbol.startsWith('clearsky')) return [symbol.endsWith('_night') ? 'moon' : 'sun','Clear'];
  if (symbol.startsWith('fair')) return [symbol.endsWith('_night') ? 'moon' : 'sun','Mostly clear'];
  if (symbol.startsWith('partlycloudy')) return ['cloud','Partly cloudy'];
  if (symbol.startsWith('cloudy')) return ['cloud','Cloudy'];
  return ['unknown','Conditions unavailable'];
}
function icon(kind) { return `<svg class="weather-icon ${kind}" viewBox="0 0 24 24" aria-hidden="true">${paths[kind]}</svg>`; }
function temperature(value, units) { return `${Math.round(units === 'fahrenheit' ? value * 9 / 5 + 32 : value)}°${units === 'fahrenheit' ? 'F' : 'C'}`; }
// Reshape the existing markup too, so cached server templates only need a refresh.
const dateRow = document.createElement('div');
dateRow.className = 'rail-date-weather';
$('#date').before(dateRow);
dateRow.append($('#date'), $('#weather-widget'));
$('#weather-toggle').replaceChildren($('#weather-icon'), $('#weather-temperature'));
$('.weather-reading')?.remove();
$('#weather-hours-panel').prepend($('#weather-location'), $('#weather-condition'));
$('#weather-hours-panel').append($('#weather-status'));
$('.weather-hours-heading strong').textContent = 'Hourly forecast';
let pinned = false;
let restoringFocus = false;
let dismissTimer;
function openHours() {
  clearTimeout(dismissTimer);
  if ($('#weather-current').hidden) return;
  $('#weather-hours-panel').hidden = false;
  $('#weather-toggle').setAttribute('aria-expanded','true');
}
function closeHours(focus = false) {
  clearTimeout(dismissTimer);
  pinned = false;
  $('#weather-hours-panel').hidden = true;
  $('#weather-toggle').setAttribute('aria-expanded','false');
  if (focus) {
    restoringFocus = true;
    $('#weather-toggle').focus();
    restoringFocus = false;
  }
}
function render(data) {
  const available = Boolean(data.current);
  $('#weather-current').hidden = !available;
  $('#weather-setup').hidden = available;
  $('#weather-widget').dataset.state = data.state;
  $('#weather-setup').innerHTML = `${icon('cloud')}<span>—</span>`;
  const setupLabel = data.state === 'disabled' ? 'Set up weather' : 'Weather unavailable. Open weather settings';
  $('#weather-setup').setAttribute('aria-label', setupLabel);
  $('#weather-setup').title = setupLabel;
  $('#weather-status').textContent = data.state === 'stale' ? 'Out of date' : data.state === 'demo' ? 'Demo weather' : data.state === 'unavailable' ? 'Weather unavailable' : '';
  $('#weather-status').title = data.message || '';
  if (!available) { closeHours(); return; }
  const [kind, description] = condition(data.current.symbol);
  $('#weather-icon').innerHTML = icon(kind);
  $('#weather-temperature').textContent = temperature(data.current.temperature,data.units);
  $('#weather-condition').textContent = description;
  $('#weather-condition').title = 'Modelled conditions for now, not a live weather-station observation.';
  $('#weather-location').textContent = data.location;
  $('#weather-location').title = data.location;
  $('#weather-toggle').disabled = false;
  $('#weather-toggle').setAttribute('aria-label', `${temperature(data.current.temperature,data.units)}, ${description}, ${data.location}${data.state === 'stale' ? ', out of date' : data.state === 'demo' ? ', demo weather' : ''}. Weather details`);
  $('#weather-hours').innerHTML = data.hours.map(row => {
    const [hourKind, label] = condition(row.symbol);
    const hour = new Date(row.time * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
    return `<li><time>${e(hour)}</time>${icon(hourKind)}<span title="${e(label)}">${e(label)}</span><b>${e(temperature(row.temperature,data.units))}</b></li>`;
  }).join('');
  $('#weather-updated').textContent = `Updated ${new Date(data.updated * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
}
let busy = false;
let lastSuccess = 0;
async function refresh() {
  if (document.hidden || busy) return;
  busy = true;
  try { render(await api('/api/weather', {timeout:15000})); lastSuccess = Date.now(); }
  catch {
    if (!lastSuccess || Date.now() - lastSuccess > 21600000) render({state:'unavailable'});
    else {
      $('#weather-status').textContent = 'Out of date';
      $('#weather-widget').dataset.state = 'stale';
      $('#weather-toggle').setAttribute('aria-label', 'Weather out of date. Open weather details');
    }
  } finally { busy = false; }
}
$('#weather-toggle').addEventListener('click', () => {
  if (pinned) closeHours();
  else { pinned = true; openHours(); }
});
$('#weather-widget').addEventListener('pointerenter', event => { if (event.pointerType === 'mouse') openHours(); });
$('#weather-widget').addEventListener('pointerleave', () => {
  if (!pinned) dismissTimer = setTimeout(() => { if (!$('#weather-widget').matches(':focus-within')) closeHours(); }, 180);
});
$('#weather-widget').addEventListener('focusin', event => { if (!restoringFocus && event.target.matches(':focus-visible')) openHours(); });
$('#weather-widget').addEventListener('focusout', event => { if (!$('#weather-widget').contains(event.relatedTarget)) closeHours(); });
$('#weather-close').addEventListener('click', () => closeHours(true));
document.addEventListener('click', event => { if (!event.target.closest('#weather-widget')) closeHours(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('#weather-hours-panel').hidden) { event.preventDefault(); closeHours(true); } });
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
setInterval(refresh,60000);
