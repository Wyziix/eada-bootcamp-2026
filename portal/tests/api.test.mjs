import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {openSqlite} from '../server/sqlite.mjs';
import {handleApi} from '../server/api.mjs';

const property={title:'Bright family home in Ames',description:'A sunny home with a spacious kitchen and a peaceful garden.',property_type:'house',price:325000,address:'123 Example Street',city:'Ames',postal_code:'50010',neighborhood:'NAmes',bedrooms:3,bathrooms:2.5,area_sqft:1500,year_built:1970,garage:2,quality:3,contact_name:'Test Owner',contact_email:'owner@example.test',contact_phone:'+1 555 0100'};
function client(db,ip=crypto.randomUUID()) {
  let cookie='';
  return {get cookie(){return cookie;},set cookie(v){cookie=v;},async call(url,method='GET',body,headers={}){
    const raw=body instanceof Uint8Array;
    const request=new Request('https://ownly.test/api'+url,{method,headers:{Origin:'https://ownly.test','CF-Connecting-IP':ip,...(cookie?{Cookie:cookie}:{}),...(body&&!raw?{'Content-Type':'application/json'}:{}),...headers},...(body!==undefined?{body:raw?body:JSON.stringify(body)}:{})});
    const response=await handleApi(request,db);
    if(response.headers.has('set-cookie'))cookie=response.headers.get('set-cookie').split(';')[0];
    const data=response.headers.get('content-type')?.includes('json')?await response.json():new Uint8Array(await response.arrayBuffer());
    return {status:response.status,headers:response.headers,data};
  },async register(email){return this.call('/register','POST',{email,password:'Ownly test password 2026!'});}};
}
const dbTest=(name,fn)=>test(name,async()=>{const db=openSqlite(':memory:');try{await fn(db);}finally{db.close();}});

dbTest('registration, password hashing, cookie sessions, expiry and logout',async db=>{
  const owner=client(db),r=await owner.register('Owner@Example.test');assert.equal(r.status,200);assert.equal(r.data.user.email,'owner@example.test');
  assert.match(r.headers.get('set-cookie'),/HttpOnly; SameSite=Lax; Max-Age=604800; Secure/);
  const user=db.native.prepare('SELECT * FROM users').get();assert.match(user.password_hash,/^pbkdf2-sha256\$100000\$/);assert.ok(!user.password_hash.includes('Ownly test'));
  const session=db.native.prepare('SELECT * FROM sessions').get();assert.notEqual(session.token_hash,owner.cookie.split('=')[1]);
  assert.equal((await owner.call('/session')).data.user.id,user.id);
  assert.equal((await client(db).register('OWNER@example.test')).status,409);
  assert.equal((await client(db).call('/login','POST',{email:'owner@example.test',password:'wrong password'})).status,401);
  const second=client(db);await second.register('second@example.test');const hash2=db.native.prepare('SELECT password_hash FROM users WHERE email=?').get('second@example.test').password_hash;assert.notEqual(user.password_hash,hash2);
  db.native.prepare('UPDATE sessions SET expires_at=0 WHERE user_id=?').run(user.id);assert.equal((await owner.call('/session')).data.user,null);
  assert.equal((await owner.call('/login','POST',{email:'owner@example.test',password:'Ownly test password 2026!'})).status,200);
  const revoked=owner.cookie;await owner.call('/logout','POST');owner.cookie=revoked;assert.equal((await owner.call('/session')).data.user,null);
  assert.equal((await owner.register('bad-email')).status,400);
});

dbTest('listing validation, contact privacy, ownership, filters and archive',async db=>{
  const anon=client(db),owner=client(db),other=client(db);await owner.register('owner@example.test');await other.register('other@example.test');
  assert.equal((await anon.call('/listings','POST',property)).status,401);
  assert.equal((await owner.call('/listings','POST',{...property,price:-1})).status,400);
  const r=await owner.call('/listings','POST',{...property,seller_id:(await other.call('/session')).data.user.id});assert.equal(r.status,201);const id=r.data.listing.id;
  const publicItem=(await anon.call('/listings')).data.listings[0];assert.equal(publicItem.title,property.title);assert.ok(!('contact_email' in publicItem));assert.ok(!('contact_phone' in publicItem));assert.ok(!('seller_id' in publicItem));
  const detail=(await anon.call('/listings/'+id)).data.listing;assert.ok(!('contact_email' in detail));assert.equal(detail.is_owner,false);
  assert.equal((await other.call('/listings/'+id)).data.listing.contact_email,property.contact_email);
  assert.equal((await owner.call('/listings/'+id)).data.listing.is_owner,true);
  for(const method of ['PUT','PATCH','DELETE'])assert.equal((await other.call('/listings/'+id,method,method==='PUT'?property:{status:'sold'})).status,404);
  assert.equal((await other.call('/me/listings')).data.listings.length,0);
  assert.equal((await owner.call('/listings/'+id,'PUT',{...property,title:'Updated bright family home'})).status,200);
  assert.equal((await anon.call('/listings?q=Ames&min_beds=3&max_price=400000&sort=price_asc')).data.total,1);
  assert.equal((await anon.call('/listings?q='+encodeURIComponent("' OR 1=1 --"))).data.total,0);
  assert.equal((await anon.call('/listings?max_price=garbage')).status,400);
  await owner.call('/listings/'+id,'PATCH',{status:'sold'});assert.equal((await anon.call('/listings')).data.total,0);assert.equal((await anon.call('/listings/'+id)).status,404);
  await owner.call('/listings/'+id,'PATCH',{status:'active'});assert.equal((await anon.call('/listings')).data.total,1);
  await owner.call('/listings/'+id,'DELETE');assert.equal((await owner.call('/me/listings')).data.listings.length,0);
});

const png=Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=','base64'));
dbTest('cover photos live in SQLite, enforce owner and supported types, disappear with archived listing',async db=>{
  const owner=client(db),other=client(db),anon=client(db);await owner.register('owner@example.test');await other.register('other@example.test');
  const id=(await owner.call('/listings','POST',property)).data.listing.id;
  assert.equal((await other.call('/listings/'+id+'/photo','PUT',png,{'Content-Type':'image/png'})).status,404);
  assert.equal((await owner.call('/listings/'+id+'/photo','PUT',new TextEncoder().encode('<svg>unsafe file</svg>'),{'Content-Type':'image/svg+xml'})).status,415);
  assert.equal((await owner.call('/listings/'+id+'/photo','PUT',new Uint8Array(768*1024+1),{'Content-Type':'image/png'})).status,413);
  const uploaded=await owner.call('/listings/'+id+'/photo','PUT',png,{'Content-Type':'image/png'});assert.equal(uploaded.status,200);
  const photo='/photos/'+uploaded.data.photo_id;assert.deepEqual((await anon.call(photo)).data,png);assert.equal(db.native.prepare('SELECT byte_length FROM listing_photos').get().byte_length,png.length);
  await owner.call('/listings/'+id,'DELETE');assert.equal((await anon.call(photo)).status,404);assert.equal((await owner.call(photo)).status,200);
});

dbTest('buyer/seller inbox supports replies, unread counts and participant authorization',async db=>{
  const owner=client(db),buyer=client(db),stranger=client(db),anon=client(db);await owner.register('owner@example.test');await buyer.register('buyer@example.test');await stranger.register('stranger@example.test');
  const listingId=(await owner.call('/listings','POST',property)).data.listing.id;
  const contact={listing_id:listingId,message:'Hello, can I arrange a viewing?'};
  assert.equal((await anon.call('/conversations','POST',contact)).status,401);assert.equal((await owner.call('/conversations','POST',contact)).status,400);
  const sent=await buyer.call('/conversations','POST',contact);assert.equal(sent.status,201);const id=sent.data.conversation_id;
  const inbox=(await owner.call('/conversations')).data.conversations;assert.equal(inbox[0].unread,1);assert.equal(inbox[0].other_email,'buyer@example.test');
  for(const suffix of ['','/read','/messages'])assert.equal((await stranger.call('/conversations/'+id+suffix,suffix?'POST':'GET',suffix==='/messages'?{message:'Intruder'}:undefined)).status,404);
  assert.equal((await stranger.call('/conversations')).data.conversations.length,0);
  await owner.call('/conversations/'+id+'/read','POST');assert.equal((await owner.call('/conversations')).data.conversations[0].unread,0);
  await owner.call('/conversations/'+id+'/messages','POST',{message:'Yes, Saturday works. <script>alert(1)</script>'});
  const messages=(await buyer.call('/conversations/'+id)).data.messages;assert.equal(messages.length,2);assert.match(messages[1].body,/<script>/); // UI must render as text, verified in browser.
  assert.equal((await buyer.call('/conversations')).data.conversations[0].unread,1);
  assert.equal((await buyer.call('/conversations','POST',contact)).data.conversation_id,id);
  await owner.call('/listings/'+listingId,'DELETE');assert.equal((await buyer.call('/conversations/'+id)).data.messages.length,3);
});

dbTest('CSRF, content type and brute-force limits are enforced',async db=>{
  const c=client(db);assert.equal((await c.call('/register','POST',{email:'x@example.test',password:'password123'},{Origin:'https://evil.test'})).status,403);
  assert.equal((await c.call('/register','POST',{email:'x@example.test',password:'password123'},{'Content-Type':'text/plain'})).status,415);
  for(let i=0;i<12;i++)assert.equal((await c.call('/login','POST',{email:'missing@example.test',password:'password123'})).status,401);
  assert.equal((await c.call('/login','POST',{email:'missing@example.test',password:'password123'})).status,429);
});

test('SQLite file and schema survive closing and reopening without duplicate migrations',async()=>{
  const dir=mkdtempSync(path.join(tmpdir(),'ownly-test-')),file=path.join(dir,'ownly.sqlite');let db=openSqlite(file);
  try{const c=client(db);await c.register('persist@example.test');await c.call('/listings','POST',property);db.close();db=openSqlite(file);
    assert.equal(db.native.prepare('SELECT count(*) AS n FROM listings').get().n,1);assert.equal(db.native.prepare('SELECT count(*) AS n FROM ownly_migrations').get().n,1);
  }finally{db.close();rmSync(dir,{recursive:true,force:true});}
});
