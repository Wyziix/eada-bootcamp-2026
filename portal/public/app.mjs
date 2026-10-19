import {adapt, validate, estimateMarketPrice} from './model.mjs';

const $ = id => document.getElementById(id);
const money = value => new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0}).format(value);
const number = value => new Intl.NumberFormat('en-US', {maximumFractionDigits:0}).format(value);
const periodLabel = period => {
  const match = /^(\d{4})Q([1-4])$/.exec(period);
  if (!match) throw new Error('Invalid market-index period');
  return `${['January–March','April–June','July–September','October–December'][Number(match[2])-1]} ${match[1]}`;
};
const qualityNames = ['Basic','Modest','Standard','High-end','Exceptional'];
const qualityDescriptions = ['Very simple materials and workmanship, with minimal detailing.','Practical, inexpensive materials and straightforward finishes.','Everyday materials, comfortable finishes, and typical workmanship.','Premium materials, thoughtful details, and above-average workmanship.','Exceptional materials, custom details, and outstanding workmanship.'];
const inputs = ['bedrooms','bathrooms','year','garage'];
const defaults = {type:'house',area:1500,quality:3,bedrooms:3,bathrooms:2,year:1970,garage:2,neighborhood:'NAmes'};
let state = {...defaults};
let units = 'sqft';
let config, marketModel, market, centers, map, lastEstimate, mapTiles;
let markers = new Map();
let tileSuccess = false;

function houseIcon(level) {
  return `<svg viewBox="0 0 32 31" aria-hidden="true"><path d="m4 15 12-11 12 11M8 12v16h16V12M13 28v-9h6v9"/>${level >= 2 ? '<path d="M10 15h2M20 15h2"/>' : ''}${level >= 3 ? '<path d="M24 7V3h-4v1M4 28h24"/>' : ''}${level >= 4 ? '<path d="M2 30h28M1 20v8M29 20v8M13 13h6"/>' : ''}${level >= 5 ? '<path d="M2 12V6M0 9h4M28 5V1M26 3h4"/>' : ''}</svg>`;
}
$('quality-options').innerHTML = qualityNames.map((name,i) => `<label class="quality-choice"><input type="radio" name="quality" value="${i+1}" ${i === 2 ? 'checked' : ''} aria-describedby="quality-description">${houseIcon(i+1)}<span>${name}</span></label>`).join('');

function updateQuality() {
  $('quality-description').replaceChildren();
  const strong = document.createElement('strong');
  strong.textContent = qualityNames[state.quality - 1] + ': ';
  $('quality-description').append(strong, qualityDescriptions[state.quality - 1]);
}

function updateAreaDisplay() {
  const metric = units === 'sqm';
  const value = metric ? Math.round(state.area / 10.7639104167 * 10) / 10 : Math.round(state.area);
  $('area').value = Number.isFinite(value) ? value : '';
  $('area').min = metric ? '27.9' : '300';
  $('area').max = metric ? '464.5' : '5000';
  $('area').step = metric ? '0.1' : '1';
  $('area-unit-label').textContent = metric ? 'm²' : 'sq ft';
  $('sqft-unit').setAttribute('aria-pressed', String(!metric));
  $('sqm-unit').setAttribute('aria-pressed', String(metric));
  $('range-min').textContent = metric ? '28 m²' : '300 sq ft';
  $('range-max').textContent = metric ? '464 m²' : '5,000 sq ft';
  updateRange();
}

function updateRange() {
  if (Number.isFinite(state.area)) $('area-range').value = state.area;
  const fill = Math.max(0, Math.min(100, ((state.area - 300) / 4700) * 100));
  $('area-range').style.setProperty('--range-fill', `${Number.isFinite(fill) ? fill : 0}%`);
  $('area-range').setAttribute('aria-valuetext', units === 'sqm' ? `${(state.area / 10.7639104167).toFixed(1)} square meters` : `${Math.round(state.area)} square feet`);
}

function updateSteppers() {
  for (const key of ['bedrooms','bathrooms']) {
    const value = Number($(key).value);
    document.querySelector(`[data-step="${key}:-1"]`).disabled = value <= Number($(key).min);
    document.querySelector(`[data-step="${key}:1"]`).disabled = value >= Number($(key).max);
  }
}

function setError(key, message) {
  const error = $(`${key}-error`);
  if (!error) return;
  error.textContent = message || '';
  error.hidden = !message;
  const control = $(key);
  if (control) {
    if (message) control.setAttribute('aria-invalid','true');
    else control.removeAttribute('aria-invalid');
  }
}

function markChanged() {
  if (!marketModel) return;
  $('estimate-button-label').textContent = lastEstimate ? 'Update my estimate' : 'Get my estimate';
  $('stale-message').hidden = !lastEstimate;
  $('result-panel').classList.toggle('is-stale', Boolean(lastEstimate));
  $('download-button').disabled = Boolean(lastEstimate);
  if (lastEstimate) $('result-status').textContent = '';
  renderAssumptions();
}

function updateType() {
  const apartment = state.type === 'apartment';
  setError('type', apartment ? 'Apartment estimates need a separate model. Choose a house or townhouse to explore Ames prices.' : '');
  if (apartment) {
    $('result-title').textContent = 'Apartments need their own model.';
    $('result-subtitle').textContent = 'The Ames dataset covers whole houses and townhouses.';
    $('result-empty').hidden = true;
    $('result-content').hidden = true;
    $('stale-message').hidden = true;
    $('result-status').textContent = 'Choose a house or townhouse to get an estimate.';
    $('estimate-button-label').textContent = 'Choose a supported home type';
    $('estimate-button').disabled = true;
  } else {
    $('estimate-button').disabled = !marketModel;
    $('result-title').textContent = lastEstimate ? 'A little more clarity.' : 'Let’s find its ballpark.';
    $('result-subtitle').textContent = 'A few familiar details. A model-backed estimate.';
    $('result-empty').hidden = Boolean(lastEstimate);
    $('result-content').hidden = !lastEstimate;
    markChanged();
  }
}

for (const key of inputs) {
  $(key).addEventListener('input', () => {
    state[key] = $(key).value.trim() === '' ? NaN : Number($(key).value);
    setError(key,'');
    updateSteppers();
    markChanged();
  });
}
$('garage').addEventListener('change', () => {state.garage = Number($('garage').value); markChanged();});
$('area').addEventListener('input', () => {
  const value = $('area').value.trim() === '' ? NaN : Number($('area').value);
  state.area = units === 'sqm' ? value * 10.7639104167 : value;
  setError('area',''); updateRange(); markChanged();
});
$('area-range').addEventListener('input', () => {state.area = Number($('area-range').value); setError('area',''); updateAreaDisplay(); markChanged();});
for (const [id,value] of [['sqft-unit','sqft'],['sqm-unit','sqm']]) $(id).addEventListener('click', () => {units = value; updateAreaDisplay();});
document.querySelectorAll('[data-step]').forEach(button => button.addEventListener('click', () => {
  const [key,delta] = button.dataset.step.split(':');
  const current = Number.isFinite(state[key]) ? state[key] : 0;
  state[key] = Math.max(Number($(key).min), Math.min(Number($(key).max), current + Number(delta)));
  $(key).value = state[key]; setError(key,''); updateSteppers(); markChanged();
}));
document.querySelectorAll('input[name=quality]').forEach(radio => radio.addEventListener('change', () => {state.quality = Number(radio.value); updateQuality(); markChanged();}));
document.querySelectorAll('input[name=type]').forEach(radio => radio.addEventListener('change', () => {state.type = radio.value; markChanged(); updateType();}));
$('neighborhood').addEventListener('change', () => selectNeighborhood($('neighborhood').value, true));

function selectNeighborhood(code, pan = false) {
  state.neighborhood = code;
  $('neighborhood').value = code;
  const n = config.neighborhoods.find(n => n.code === code);
  $('neighborhood-name').textContent = n.name;
  $('neighborhood-count').textContent = `${number(n.count)} training sales · 2006–2009`;
  for (const [key,marker] of markers) {
    marker.setIcon(markerIcon(key));
    marker.setZIndexOffset(key === code ? 1000 : 0);
    const el = marker.getElement();
    if (el) el.setAttribute('aria-label', `${config.neighborhoods.find(n => n.code === key).name}${key === code ? ', selected' : ''}`);
  }
  if (pan && map && centers.centers[code]) map.panTo(centers.centers[code], {animate:false});
  markChanged();
}

function markerIcon(code) {
  const selected = state.neighborhood === code;
  const n = config.neighborhoods.find(n => n.code === code);
  return L.divIcon({className:`neighborhood-marker${selected ? ' selected' : ''}`,html:`<span class="marker-core">${selected ? `<span class="marker-label">${n.name}</span>` : ''}</span>`,iconSize:[24,24],iconAnchor:[12,12]});
}

function initMap() {
  if (!window.L) {$('map-fallback').hidden = false; $('map-reset').hidden = true; return;}
  map = L.map('map', {scrollWheelZoom:false,zoomControl:false,attributionControl:true,zoomSnap:.25});
  L.control.zoom({position:'topright'}).addTo(map);
  mapTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom:18,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'});
  mapTiles.on('tileload', () => {tileSuccess = true; $('map-fallback').hidden = true;});
  mapTiles.on('tileerror', () => {if (!tileSuccess) $('map-fallback').hidden = false;});
  mapTiles.addTo(map);
  const bounds = L.latLngBounds(Object.values(centers.centers));
  map.fitBounds(bounds.pad(.12));
  for (const n of config.neighborhoods) {
    const point = centers.centers[n.code];
    if (!point) continue;
    const marker = L.marker(point, {icon:markerIcon(n.code),keyboard:true,title:n.name,alt:`${n.name} neighborhood`}).addTo(map);
    marker.bindTooltip(n.name, {direction:'top',offset:[0,-9]});
    marker.on('click', () => selectNeighborhood(n.code));
    markers.set(n.code, marker);
  }
  $('map-reset').addEventListener('click', () => map.fitBounds(bounds.pad(.12), {animate:false}));
  new ResizeObserver(() => map.invalidateSize({pan:false})).observe($('map'));
}

function renderAssumptions() {
  if (!config || state.type === 'apartment' || !config.profiles[state.neighborhood] || Object.keys(validate(state,config)).length) return;
  const row = adapt(state,config);
  const profile = config.profiles[state.neighborhood][state.type];
  const lines = [
    ['Starting example', profile.count ? `${profile.count} training ${state.type === 'house' ? 'houses' : 'townhouses'} in this neighborhood` : `No training ${state.type === 'house' ? 'houses' : 'townhouses'} here; example from elsewhere in Ames`],
    ['Lot area',`${number(row['Lot Area'])} sq ft`],
    ['Basement area',`${number(row['Total Bsmt SF'])} sq ft`],
    ['Half bathrooms',String(row['Half Bath'])],
    ['Last remodel / addition',String(row['Year Remod/Add'])],
    ['Garage area',`${number(row['Garage Area'])} sq ft`],
    ['Maintenance condition',`${row['Overall Cond']} / 10 (from the example)`],
    ...(market ? [
      ['Price reference',`${periodLabel(market.reference_period)}, common market-price period`],
      ['Market estimate',`${periodLabel(market.target_period)} · Ames metropolitan index`],
      ['Market adjustment',`×${market.adjustment_factor.toFixed(3)} · no automatic property changes`],
    ] : []),
  ];
  $('assumption-details').replaceChildren();
  for (const [key,value] of lines) {
    const term = document.createElement('dt'); term.textContent = key;
    const definition = document.createElement('dd'); definition.textContent = value;
    $('assumption-details').append(term,definition);
  }
}

function getEstimate(event) {
  event.preventDefault();
  if (!marketModel) return;
  const errors = validate(state,config);
  for (const key of ['type','area','year','bedrooms','bathrooms','garage','quality','neighborhood']) setError(key, errors[key]);
  if (Object.keys(errors).length) {
    const key = Object.keys(errors)[0];
    ($(key) || document.querySelector(`input[name="${key}"]`))?.focus();
    $('result-status').textContent = 'Check the highlighted details before estimating.';
    return;
  }
  $('result-panel').setAttribute('aria-busy','true');
  try {
    const features = adapt(state, config);
    const marketResult = estimateMarketPrice(features, marketModel, market);
    const price = marketResult.price;
    if (!Number.isFinite(price) || price <= 0) throw new Error('Invalid model output');
    const n = config.neighborhoods.find(n => n.code === state.neighborhood);
    const activeFeatures = Object.fromEntries([...marketModel.numeric,...marketModel.categorical.map(c=>c.column)].map(c=>[c,features[c]]));
    lastEstimate = {created_at:new Date().toISOString(),scope:`Ames, Iowa; ${market.target_period} market-adjusted estimate; accuracy for this period has not been measured`,
      supplied_inputs:{...state},quality_label:qualityNames[state.quality-1],predicted_sale_price_usd:price,
      neighborhood_name:n.name,model_name:marketModel.name,model_sha256:marketModel.sha256,
      reference_price_usd:marketResult.reference,reference_period:market.reference_period,
      estimate_period:market.target_period,index_adjustment_factor:marketResult.factor,
      market_index_source:market.index_source,measured_accuracy_for_estimate_period:null,
      simplified_form_validation:market.simplified_validation,
      assumptions:'Unasked features are from a representative 2006–2009 training property. Garage area assumes 240 sq ft per car. Full inputs are included below. ' + market.scenario_assumptions,model_inputs:activeFeatures};
    $('price').textContent = money(Math.round(price / 1000) * 1000);
    $('result-title').textContent = 'A little more clarity.';
    $('result-subtitle').textContent = 'Your home’s estimate, adjusted to the latest published Ames market.';
    $('result-price-period').textContent = `${market.target_period.slice(0,4)} market-adjusted estimate · USD`;
    $('reference-price').textContent = money(Math.round(marketResult.reference / 1000)*1000);
    $('reference-period-label').textContent = `Reference value · ${periodLabel(market.reference_period)}`;
    $('market-factor').textContent = `× ${marketResult.factor.toFixed(3)}`;
    $('market-index-date').textContent = `Index: ${periodLabel(market.target_period)} · published ${market.index_source.source_release_date}`;
    const size = units === 'sqm' ? `${number(state.area / 10.7639104167)} m²` : `${number(state.area)} sq ft`;
    $('result-summary').replaceChildren();
    const parts = [n.name,size,`${state.bedrooms} bed`,`${state.bathrooms} full bath`,qualityNames[state.quality-1]];
    parts.forEach((part,i) => {
      if (i) {const bullet = document.createElement('span'); bullet.className = 'bullet'; bullet.textContent = '·'; $('result-summary').append(bullet);}
      const span = document.createElement('span'); span.textContent = part; $('result-summary').append(span);
    });
    $('result-empty').hidden = true; $('result-content').hidden = false; $('stale-message').hidden = true;
    $('result-panel').classList.remove('is-stale');
    $('download-button').disabled = false;
    $('estimate-button-label').textContent = 'Estimate again';
    const count = config.profiles[state.neighborhood][state.type].count;
    $('result-status').textContent = `Market-adjusted estimate: ${$('price').textContent}.${count < 10 ? ` Limited local examples: ${count} ${state.type === 'house' ? 'houses' : 'townhouses'} in this neighborhood’s training data.` : ''}`;
    renderAssumptions();
    if (matchMedia('(max-width:760px)').matches) $('result-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches ? 'instant' : 'smooth',block:'start'});
  } catch {
    $('result-status').textContent = 'We couldn’t calculate this estimate. Please check your details and try again.';
  } finally {$('result-panel').setAttribute('aria-busy','false');}
}
$('home-form').addEventListener('submit',getEstimate);
$('download-button').addEventListener('click', () => {
  if (!lastEstimate || $('download-button').disabled) return;
  const data = {...lastEstimate,displayed_price_usd:Math.round(lastEstimate.predicted_sale_price_usd / 1000) * 1000};
  const blob = new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = `ownly-${lastEstimate.supplied_inputs.neighborhood.toLowerCase()}-estimate.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url),1000);
  $('result-status').textContent = 'Estimate saved with your answers, assumptions, and full model inputs.';
});
$('reset-button').addEventListener('click', () => {
  state = {...defaults}; units = 'sqft'; lastEstimate = null;
  for (const key of inputs) $(key).value = defaults[key];
  document.querySelector('input[name=type][value=house]').checked = true;
  document.querySelector('input[name=quality][value="3"]').checked = true;
  $('result-empty').hidden = false; $('result-content').hidden = true; $('stale-message').hidden = true;
  $('result-status').textContent = ''; $('result-panel').classList.remove('is-stale');
  for (const key of ['type','area','year','bedrooms','bathrooms','garage','quality','neighborhood']) setError(key,'');
  updateAreaDisplay(); updateSteppers(); updateQuality(); updateType();
  if (config) selectNeighborhood(defaults.neighborhood,true);
});
document.querySelectorAll('[data-dialog]').forEach(button => button.addEventListener('click', () => $(button.dataset.dialog).showModal()));
document.querySelectorAll('dialog').forEach(dialog => {
  dialog.querySelector('.dialog-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {if (event.target === dialog) {const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();}});
});
updateAreaDisplay(); updateQuality(); updateSteppers();

async function json(url) {const response = await fetch(url); if (!response.ok) throw new Error(`Unable to load ${url}`); return response.json();}
try {
  [config,centers,marketModel,market] = await Promise.all(['./assets/config.json','./assets/neighborhood-centers.json','./assets/market-model.json','./assets/market.json'].map(json));
  if (marketModel.sha256 !== market.model_sha256) throw new Error('Mismatched reference model');
  $('neighborhood').replaceChildren();
  for (const n of config.neighborhoods) {const option = document.createElement('option'); option.value = n.code; option.textContent = n.name; $('neighborhood').append(option);}
  $('neighborhood').disabled = false;
  $('estimate-button').disabled = false;
  $('estimate-button-label').textContent = 'Get my estimate';
  $('result-panel').setAttribute('aria-busy','false');
  $('dialog-mae').textContent = money(Math.round(market.simplified_validation.mae));
  $('dialog-within').textContent = `${Math.round(market.simplified_validation.within_20)}%`;
  $('dialog-market-calculation').textContent = `${market.target_index.toFixed(2)} / ${market.reference_index.toFixed(2)} = ${market.adjustment_factor.toFixed(3)}`;
  $('dialog-market-description').textContent = `The reference prediction is multiplied by this factor, using the Ames metropolitan index for ${periodLabel(market.target_period)} relative to ${periodLabel(market.reference_period)}. The source was published on ${market.index_source.source_release_date}. Estimates use the latest period in the bundled index snapshot; no later quarters are guessed.`;
  try {initMap();} catch {$('map-fallback').hidden = false; $('map-reset').hidden = true;}
  // Listing links may supply known details; validation still enforces the model's coverage.
  const query = new URLSearchParams(location.search);
  for (const key of ['area','quality',...inputs]) if(query.has(key) && Number.isFinite(Number(query.get(key)))) state[key]=Number(query.get(key));
  if(['house','townhouse'].includes(query.get('type')))state.type=query.get('type');
  const locationInput=query.get('neighborhood');
  const selected=config.neighborhoods.find(n=>n.code.toLowerCase()===locationInput?.toLowerCase() || n.name.toLowerCase()===locationInput?.toLowerCase());
  if(selected)state.neighborhood=selected.code;
  for(const key of inputs)$(key).value=state[key];
  document.querySelector('input[name=type][value="'+state.type+'"]').checked=true;
  document.querySelector('input[name=quality][value="'+(state.quality>=1&&state.quality<=5&&Number.isInteger(state.quality)?state.quality:3)+'"]').checked=true;
  updateAreaDisplay();updateQuality();updateSteppers();updateType();
  selectNeighborhood(state.neighborhood);
} catch {
  $('estimate-button').disabled = true;
  $('estimate-button-label').textContent = 'Model unavailable';
  $('result-panel').setAttribute('aria-busy','false');
  $('load-error').hidden = false;
  $('load-error').textContent = 'The model files could not be loaded. Refresh to try again. If you opened this as a local file, start the portal with “npm run dev” and open http://127.0.0.1:8850.';
}
