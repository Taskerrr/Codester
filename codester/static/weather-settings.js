import {$, api} from './common.js';

let selected = null;
let generation = 0;
function selectionLabel() {
  $('#weather-selected').textContent = selected ? `Selected: ${selected.location}` : 'No location selected';
  $('#weather-clear').disabled = !selected;
}
function changed() { $('#weather-enabled').dispatchEvent(new Event('change',{bubbles:true})); }
export function fillWeather(config) {
  if (!$('#weather-settings')) return; // Older cached templates can remain open until restart.
  $('#weather-settings').disabled = false;
  generation += 1;
  selected = config?.location ? {location:config.location,latitude:config.latitude,longitude:config.longitude} : null;
  $('#weather-enabled').checked = Boolean(config?.enabled);
  $('#weather-units').value = config?.units || 'celsius';
  $('#weather-results').replaceChildren();
  $('#weather-search-status').textContent = '';
  selectionLabel();
}
export function readWeather() {
  if (!$('#weather-settings')) return undefined;
  return {enabled:$('#weather-enabled').checked, units:$('#weather-units').value,
    ...(selected || {location:'',latitude:null,longitude:null})};
}
async function search() {
  const query = $('#weather-query').value.trim();
  if (query.length < 2) { $('#weather-search-status').textContent = 'Enter a town or city.'; return; }
  const request = ++generation;
  $('#weather-search').disabled = true;
  $('#weather-results').replaceChildren();
  $('#weather-search-status').textContent = 'Finding towns…';
  try {
    const data = await api('/api/weather/locations',{method:'POST',body:JSON.stringify({query}),timeout:15000});
    if (generation !== request) return;
    $('#weather-search-status').textContent = data.locations.length ? 'Choose a location, then save settings.' : 'No towns found. Try adding the country.';
    for (const location of data.locations) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'secondary-button';
      button.textContent = location.location;
      button.addEventListener('click', () => {
        selected = location;
        $('#weather-enabled').checked = true;
        $('#weather-results').replaceChildren();
        $('#weather-search-status').textContent = 'Location selected. Save settings to apply.';
        selectionLabel();
        changed();
        $('#weather-query').focus();
      });
      $('#weather-results').append(button);
    }
  } catch (error) { if (generation === request) $('#weather-search-status').textContent = error.message; }
  finally { $('#weather-search').disabled = false; }
}
$('#weather-search')?.addEventListener('click',search);
$('#weather-query')?.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); if (!$('#weather-search').disabled) search(); } });
$('#weather-query')?.addEventListener('input', () => { generation += 1; $('#weather-results').replaceChildren(); $('#weather-search-status').textContent = ''; });
$('#weather-clear')?.addEventListener('click', () => {
  generation += 1;
  selected = null;
  $('#weather-enabled').checked = false;
  $('#weather-results').replaceChildren();
  $('#weather-search-status').textContent = 'Save settings to clear the location.';
  selectionLabel();
  changed();
});
