# Ownly

Ownly is a private property portal with email/password accounts, owner listings, cover photos, buyer–seller conversations, and the existing Ames home valuation tool. One account can buy and sell. Registration checks the email's format but sends no verification email. Messages stay in the Ownly inbox; no outgoing email service is configured.

## Run locally

Use Node.js 22.13 or newer with the built-in SQLite module:

```bash
npm install
npm run dev
```

Open http://127.0.0.1:8850. The local server automatically applies the schema migrations once, then stores accounts, listings, photos, and messages in `.data/ownly.sqlite`. This directory is ignored by Git. Stop the server before copying the database for a backup, including its WAL/SHM sidecars if present. `OWNLY_PORT` and `OWNLY_DB_PATH` override the defaults. No Python process is needed for predictions.

## Use Ownly

- Browse and filter real listings without creating an Ownly account. Empty databases show an invitation to post the first property; there are no seeded or invented listings.
- Register with email and a password of at least eight characters. No email confirmation is required. Sign out and return using the same credentials.
- Publish a property with its address, price in USD, description, specifications, seller contact details, and an optional cover photo. Edit it, mark it sold, make it available again, or remove it from browsing.
- Registered buyers can view contact email/phone and send an initial inquiry. Both parties can reply in the inbox. Other accounts cannot read those conversations or edit the property. Removed listings retain their conversation history.
- Upload one JPEG, PNG, or WebP cover photo up to 10 MB. The browser resizes it to at most 1,600 pixels on the longest side and 768 KiB. The image bytes live in SQLite, alongside the records.

The hosted Site retains its existing owner-private Sites access boundary. Ownly accounts work inside that boundary; registering an Ownly account does not grant access through the outer Sites access policy. Keep it private during testing, as requested.

## Storage and hosting

Locally, `server/sqlite.mjs` adapts Node's SQLite API to the D1 query interface. The hosted Worker uses Cloudflare D1, a SQLite-based database declared as `DB` in `.openai/hosting.json`. The shared `server/api.mjs` serves both environments. No external SQL server or R2 bucket is required.

`db/schema.ts` is the Drizzle schema; `drizzle/` contains the generated schema-only SQL and metadata. To change the schema, edit the source and run `npm run db:generate`. Sites applies the committed migrations during publication. Request handlers never create tables or seed records. Local and hosted databases are separate; local test accounts and properties are not published.

Passwords use salted PBKDF2-SHA256 with 100,000 iterations, within the current Workers WebCrypto limit. Random seven-day session tokens are held in HttpOnly, SameSite=Lax cookies (Secure on HTTPS); only SHA-256 token hashes are stored. Logout revokes the token. The API checks the request origin, validates inputs, uses SQL parameters, throttles authentication and messages, and checks listing ownership and conversation participation on every protected operation. Contact email/phone are excluded from unauthenticated responses. There is no password recovery flow in this version.

Build the Worker through the Sites helper. For a local built-Worker check, apply the generated migration to local D1 before `npm start`:

```bash
node /path/to/sites-plugin/scripts/build-site.mjs
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_smart_machine_man.sql
npm start -- --port 8851
```

Keep the generated build out of source control. `frontend/` contains the marketplace and estimator HTML; `public/` contains their assets. The root route returns the marketplace HTML, and `app/api/[...path]/route.ts` connects the shared API to D1. Publication uses the existing Sites project and its private deployment workflow.

## Valuation model

The valuation tool always uses the market-adjusted companion model with the latest published period in its bundled index snapshot, currently 2026Q2. There is no price-period selector. A supported listing can open the estimator with its known details filled in. The asking price remains the owner's choice.

`public/model.mjs` reproduces the saved scikit-learn preprocessing and compact histogram boosting pipeline in the browser. `public/assets/market-model.json` is tied to the reference joblib checksum. Predictions require no server inference call. The older historical model remains available to parity tests and the original benchmark.

The companion model fits 2,589 sales from 2006–2009 with 75 predictors; sale year and month are excluded. Training prices are normalized to 2010Q2. The reference prediction is multiplied by `324.78 / 166.78 = 1.947355798`, the revised Ames metropolitan FHFA index ratio for 2026Q2 relative to 2010Q2. The index includes sales and appraisals and is not seasonally adjusted. Source metadata and checksums are in `public/assets/market.json` and the parent project's `dat/market/`.

The valuation coverage remains Ames houses/townhouses constructed in 1872–2010, living area 300–5,000 sq ft, 0–8 bedrooms, 0–5 full bathrooms, and 0–4 garage spaces. The simplified form fills unasked characteristics from representative training homes. Listings may describe a wider range of properties, but that does not expand the model's coverage. There is no measured 2026 property-level accuracy; the model and index are learning aids and approximate estimates. The snapshot must be refreshed when newer index periods are published.

## Validation and model export

```bash
npm test
```

The model tests compare 341 full-feature and 317 simplified-form historical predictions to Python, and the same rows in the market-adjusted scenario, to sub-cent tolerance. They also test all 28 neighborhoods, supported home types, validation boundaries, and period metadata. API tests cover account/session behavior, SQL persistence, listing/contact access, ownership, photos, inbox participation, revocation, request-origin checks, and rate limits.

To refresh browser model assets from the parent project without retraining:

```bash
source ~/myenv/bin/activate
python scripts/export_portal_model.py
```

Run that command from the parent directory. Source model data and original KPI reports remain in the parent project. See its `README.md` for the benchmark, current-year adjustment, and offline HTML reports.

## Map attribution

The estimator bundles [Leaflet 1.9.4](https://leafletjs.com), with its BSD license under `public/vendor/leaflet/LICENSE`. Live map tiles are © OpenStreetMap contributors with visible attribution. Approximate neighborhood centers are aggregated from [Max Kuhn's AmesHousing](https://github.com/topepo/AmesHousing) geodata. `public/assets/neighborhood-centers.json` records provenance; individual source parcel IDs are not deployed.
