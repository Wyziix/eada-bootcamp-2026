import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {predict,adapt,validate,estimateMarketPrice} from '../public/model.mjs';
const read = async file => JSON.parse(await readFile(new URL(file, import.meta.url), 'utf8'));
const [model,config,fixtures,geodata] = await Promise.all(['../public/assets/model.json','../public/assets/config.json','./fixtures.json','../public/assets/neighborhood-centers.json'].map(read));
let worst = 0;
fixtures.rows.forEach((row,i) => {
  const result = predict(row,model);
  const delta = Math.abs(result - fixtures.predictions[i]);
  worst = Math.max(worst,delta);
  assert.ok(delta < 0.00001, `Python/browser model disagreement at held-out row ${i}: ${delta}`);
});
fixtures.forms.forEach((form,i) => {
  const delta = Math.abs(predict(adapt(form,config),model) - fixtures.adapted_predictions[i]);
  assert.ok(delta < 0.00001, `Python/browser simplified-form disagreement at row ${i}: ${delta}`);
});
const example = {type:'house',area:1500,quality:3,bedrooms:3,bathrooms:2,year:1970,garage:2,neighborhood:'NAmes'};
assert.deepEqual(validate(example,config),{});
for (const invalid of [{area:NaN},{area:Infinity},{area:0},{area:5001},{year:2026},{year:1970.5},{type:'apartment'},{quality:0},{bedrooms:9},{bathrooms:1.5},{neighborhood:'Boston'}]) {
  assert.ok(Object.keys(validate({...example,...invalid},config)).length, `Invalid form accepted: ${JSON.stringify(invalid)}`);
}
for (const type of ['house','townhouse']) for (const n of config.neighborhoods) {
  const form = {...example,type,neighborhood:n.code};
  assert.deepEqual(validate(form,config),{});
  assert.ok(Number.isFinite(predict(adapt(form,config),model)));
  assert.ok(geodata.centers[n.code],`Missing map coordinate: ${n.code}`);
}
const noGarage = adapt({...example,garage:0},config);
assert.equal(noGarage['Garage Area'],0);
assert.equal(noGarage['Garage Type'],'NA');
assert.equal(noGarage['Garage Yr Blt'],null);
console.log(`PASS: all ${fixtures.rows.length} original Python predictions match JavaScript (largest difference $${worst}).`);
console.log(`PASS: all ${fixtures.forms.length} simplified-form Python predictions match JavaScript.`);
console.log(`PASS: invalid inputs rejected; all 28 neighborhoods work for both home types; no-garage assumptions consistent.`);

const [marketModel,market,marketFixtures] = await Promise.all(['../public/assets/market-model.json','../public/assets/market.json','./market-fixtures.json'].map(read));
assert.ok(!marketModel.numeric.includes('Yr Sold') && !marketModel.numeric.includes('Mo Sold'));
assert.equal(market.accuracy_2026,null);
assert.equal(market.reference_period,'2010Q2');
assert.equal(market.target_period,'2026Q2');
assert.ok(Math.abs(market.adjustment_factor-324.78/166.78)<1e-12);
let marketWorst = 0;
marketFixtures.rows.forEach((row,i) => {
  const estimate = estimateMarketPrice(row,marketModel,market);
  marketWorst = Math.max(marketWorst, Math.abs(estimate.price-marketFixtures.scenario_predictions[i]));
  assert.ok(Math.abs(estimate.reference-marketFixtures.reference_predictions[i])<.00001, `Reference prediction mismatch at ${i}`);
  assert.ok(Math.abs(estimate.price-marketFixtures.scenario_predictions[i])<.00001, `Market scenario mismatch at ${i}`);
  assert.equal(predict({...row,'Yr Sold':2026,'Mo Sold':12},marketModel),estimate.reference, 'Calendar inputs must not be extrapolated in the reference model');
});
marketFixtures.forms.forEach((form,i) => {
  const estimate = estimateMarketPrice(adapt(form,config),marketModel,market);
  assert.ok(Math.abs(estimate.reference-marketFixtures.adapted_reference_predictions[i])<.00001);
  assert.ok(Math.abs(estimate.price-marketFixtures.adapted_scenario_predictions[i])<.00001);
});
for (const type of ['house','townhouse']) for (const n of config.neighborhoods) {
  const form = {...example,type,neighborhood:n.code};
  assert.deepEqual(validate(form,config),{});
  assert.ok(Number.isFinite(estimateMarketPrice(adapt(form,config),marketModel,market).price));
}
assert.throws(()=>estimateMarketPrice(example,model,market),/does not match/);
for (const invalid of [{adjustment_factor:Infinity},{adjustment_factor:2},{target_index:-1},{target_period:'2026Q3'},{model_sha256:'wrong-file'}]) {
  assert.throws(()=>estimateMarketPrice(marketFixtures.rows[0],marketModel,{...market,...invalid}));
}
console.log(`PASS: ${marketFixtures.rows.length} full and ${marketFixtures.forms.length} simplified 2026 scenarios match Python; largest dollar difference ${marketWorst}.`);
console.log('PASS: historical calendar cannot alter reference predictions; invalid market metadata and unsupported periods rejected; all neighborhoods work in 2026 mode.');
