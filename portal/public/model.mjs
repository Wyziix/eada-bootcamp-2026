export const QUALITY = [2, 4, 5, 7, 9];

export function predict(features, model) {
  const missing = model.numeric.map(c => features[c] == null || features[c] === '');
  const numeric = model.numeric.map((c,i) => missing[i] ? model.medians[i] : Number(features[c]));
  numeric.push(...model.indicators.map(i => Number(missing[i])));
  const vector = numeric.map((n,i) => (n - model.mean[i]) / model.scale[i]);
  for (const c of model.categorical) {
    const raw = features[c.column];
    const value = raw == null || raw === '' ? '__MISSING__' : String(raw);
    const index = Object.hasOwn(c.mapping, value) ? c.mapping[value] : c.unknown;
    for (let i = 0; i < c.size; i++) vector.push(Number(i === index));
  }
  let output = model.baseline;
  for (const tree of model.trees) {
    let node = tree[0];
    while (!node[5]) {
      const value = vector[node[1]];
      node = tree[Number.isNaN(value) ? (node[6] ? node[3] : node[4]) : (value <= node[2] ? node[3] : node[4])];
    }
    output += node[0];
  }
  return Math.expm1(output);
}

export function validate(form, config) {
  const errors = {};
  if (!config.profiles[form.neighborhood]) errors.neighborhood = 'Choose a neighborhood from the list.';
  if (!['house','townhouse'].includes(form.type)) errors.type = 'This model covers houses and townhouses. Apartment estimates need a separate model.';
  for (const [key, min, max, label] of [
    ['area',300,5000,'Enter a living area between 300 and 5,000 sq ft (28–464 m²).'],
    ['year',1872,2010,'Enter a year between 1872 and 2010, the model’s historical coverage.'],
    ['bedrooms',0,8,'Choose between 0 and 8 bedrooms.'],
    ['bathrooms',0,5,'Choose between 0 and 5 full bathrooms.'],
    ['garage',0,4,'Choose between 0 and 4 garage spaces.'],
    ['quality',1,5,'Choose one of the five quality levels.'],
  ]) {
    if (!Number.isFinite(form[key]) || form[key] < min || form[key] > max || (key !== 'area' && !Number.isInteger(form[key]))) errors[key] = label;
  }
  return errors;
}

export function adapt(form, config) {
  const profile = config.profiles[form.neighborhood][form.type];
  const row = {...profile.features};
  const fraction = row['2nd Flr SF'] / Math.max(row['Gr Liv Area'], 1);
  Object.assign(row, {
    'Neighborhood':form.neighborhood, 'Gr Liv Area':form.area, 'Overall Qual':QUALITY[form.quality - 1],
    'Year Built':form.year, 'Year Remod/Add':Math.max(form.year, row['Year Remod/Add']),
    'Bedroom AbvGr':form.bedrooms, 'Full Bath':form.bathrooms,
    'Garage Cars':form.garage, 'Garage Area':form.garage * 240,
    '1st Flr SF':Math.round(form.area * (1 - fraction)), '2nd Flr SF':Math.round(form.area * fraction),
    'Low Qual Fin SF':0, 'TotRms AbvGrd':Math.max(form.bedrooms + 3, 4),
  });
  if (form.garage === 0) Object.assign(row, {'Garage Type':'NA','Garage Yr Blt':null,'Garage Finish':'NA','Garage Qual':'NA','Garage Cond':'NA'});
  else if (!row['Garage Yr Blt']) Object.assign(row, {'Garage Type':'Attchd','Garage Yr Blt':form.year,'Garage Finish':'Unf','Garage Qual':'TA','Garage Cond':'TA'});
  return row;
}

export function estimateMarketPrice(features, model, market) {
  if (model.sha256 !== market.model_sha256 || model.numeric.includes('Yr Sold') || model.numeric.includes('Mo Sold')) {
    throw new Error('The reference-price model does not match the market scenario.');
  }
  const factor = market.target_index / market.reference_index;
  if (![market.reference_index, market.target_index, factor].every(v => Number.isFinite(v) && v > 0)
      || !Number.isFinite(market.adjustment_factor) || Math.abs(factor - market.adjustment_factor) > 1e-12
      || market.target_period !== market.index_source.latest_period) {
    throw new Error('A published, matching market-index period is required.');
  }
  const reference = predict(features, model);
  const price = reference * factor;
  if (!Number.isFinite(price) || price <= 0) throw new Error('Invalid market estimate.');
  return {reference, price, factor};
}
