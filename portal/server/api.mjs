// Shared Web-standard API: Cloudflare D1 in production, SQLite locally.
const SESSION_MS = 7 * 24 * 60 * 60 * 1000;
const HASH_ITERATIONS = 100000; // Current workerd WebCrypto per-call limit.
const encoder = new TextEncoder();
const MAX_PHOTO = 768 * 1024;
const PHOTO_PATH = /^\/api\/photos\/([a-f0-9-]{36})$/;
const LISTING_PATH = /^\/api\/listings\/([a-f0-9-]{36})(\/photo)?$/;
const CONVERSATION_PATH = /^\/api\/conversations\/([a-f0-9-]{36})(\/messages|\/read)?$/;
const PUBLIC_COLUMNS = `l.id,l.title,l.description,l.property_type,l.address,l.city,l.postal_code,l.neighborhood,
  l.price,l.bedrooms,l.bathrooms,l.area_sqft,l.year_built,l.garage,l.quality,l.status,l.created_at,l.updated_at,
  l.contact_name,(SELECT p.id FROM listing_photos p WHERE p.listing_id=l.id) AS photo_id`;

class HttpError extends Error {
  constructor(status, message, field) { super(message); this.status=status; this.field=field; }
}
const fail = (status,message,field) => { throw new HttpError(status,message,field); };
const hex = bytes => [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,"0")).join("");
const unhex = value => Uint8Array.from(value.match(/../g) || [], byte=>parseInt(byte,16));
const random = size => hex(crypto.getRandomValues(new Uint8Array(size)));
const digest = async value => hex(await crypto.subtle.digest("SHA-256",encoder.encode(value)));
const rows = async statement => (await statement.all()).results;
const stmt = (db,sql,...values) => db.prepare(sql).bind(...values);

function json(data,status=200,headers={}) {
  return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff",...headers}});
}
async function body(request,limit=32768) {
  if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/json")) fail(415,"Send JSON data.");
  if (Number(request.headers.get("content-length")) > limit) fail(413,"The request is too large.");
  const source=await request.text();
  if(encoder.encode(source).length>limit) fail(413,"The request is too large.");
  try {const value=JSON.parse(source);if(!value || Array.isArray(value) || typeof value!=="object")throw Error();return value;}
  catch {fail(400,"The request could not be read. Please try again.");}
}
function text(value,field,min=0,max=200) {
  if(typeof value!=="string") fail(400,`Please enter ${field.replaceAll("_"," ")}.`,field);
  value=value.trim();
  if(value.length<min || value.length>max || /\u0000/.test(value)) fail(400,`${field.replaceAll("_"," ")} must be ${min}–${max} characters.`,field);
  return value;
}
function email(value,field="email") {
  const result=text(value,field,3,254).toLowerCase();
  if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(result)) fail(400,"Enter an email address in the usual format.",field);
  return result;
}
function number(value,field,min,max,step=1) {
  if(typeof value!=="number" || !Number.isFinite(value) || value<min || value>max || Math.abs(value/step-Math.round(value/step))>1e-7)
    fail(400,`Enter a valid ${field.replaceAll("_"," ")} between ${min} and ${max}.`,field);
  return value;
}
function cookieToken(request) {
  const value=(request.headers.get("cookie") || "").split(";").map(c=>c.trim()).find(c=>c.startsWith("ownly_session="))?.slice(14);
  return value && /^[a-f0-9]{64}$/.test(value) ? value : null;
}
function cookie(request,token,maxAge=SESSION_MS/1000) {
  return `ownly_session=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}${new URL(request.url).protocol==="https:"?"; Secure":""}`;
}
async function currentUser(request,db) {
  const token=cookieToken(request);
  return token ? await stmt(db,`SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?`,await digest(token),Date.now()).first() : null;
}
async function requireUser(request,db) {
  const user=await currentUser(request,db);if(!user)fail(401,"Sign in to continue.");return user;
}
async function passwordHash(password,salt=random(16),iterations=HASH_ITERATIONS) {
  const key=await crypto.subtle.importKey("raw",encoder.encode(password),"PBKDF2",false,["deriveBits"]);
  const bits=await crypto.subtle.deriveBits({name:"PBKDF2",hash:"SHA-256",salt:unhex(salt),iterations},key,256);
  return `pbkdf2-sha256$${iterations}$${salt}$${hex(bits)}`;
}
async function verifyPassword(password,record) {
  const [scheme,count,salt,expected]=(record || "").split("$");
  if(scheme!=="pbkdf2-sha256" || Number(count)!==HASH_ITERATIONS || !/^[a-f0-9]{32}$/.test(salt || "") || !/^[a-f0-9]{64}$/.test(expected || "")) {
    await passwordHash(password,"0".repeat(32));return false;
  }
  const actual=(await passwordHash(password,salt,Number(count))).split("$")[3];
  let difference=0;for(let i=0;i<expected.length;i++)difference|=actual.charCodeAt(i)^expected.charCodeAt(i);
  return difference===0;
}
async function rateLimit(db,key,limit,windowMs) {
  const now=Date.now(),start=now-windowMs;
  await stmt(db,`INSERT INTO auth_limits(key,hits,window_start) VALUES(?,1,?)
    ON CONFLICT(key) DO UPDATE SET hits=CASE WHEN window_start<? THEN 1 ELSE hits+1 END,
    window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END`,key,now,start,start).run();
  const record=await stmt(db,"SELECT hits FROM auth_limits WHERE key=?",key).first();
  if(record.hits>limit)fail(429,"Too many attempts. Please wait a few minutes and try again.");
}
async function signIn(request,db,user) {
  const now=Date.now(),token=random(32),old=cookieToken(request);
  const statements=[stmt(db,"DELETE FROM sessions WHERE expires_at<?",now)];
  if(old)statements.push(stmt(db,"DELETE FROM sessions WHERE token_hash=?",await digest(old)));
  statements.push(stmt(db,"INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",await digest(token),user.id,now+SESSION_MS,now));
  await db.batch(statements);
  return json({user:{id:user.id,email:user.email,name:user.name}},200,{"Set-Cookie":cookie(request,token)});
}
async function authenticate(request,db,register) {
  const values=await body(request,4096),address=email(values.email);
  if(typeof values.password!=="string" || values.password.length<8 || values.password.length>128)fail(400,"Use a password with 8–128 characters.","password");
  const ip=request.headers.get("cf-connecting-ip") || "local";
  await rateLimit(db,"auth-ip:"+await digest(ip),40,15*60*1000);
  await rateLimit(db,"auth-email:"+await digest(address),12,15*60*1000);
  if(register) {
    const name=text(values.name || address.split("@")[0],"name",1,80),id=crypto.randomUUID(),hash=await passwordHash(values.password),now=Date.now();
    try {await stmt(db,"INSERT INTO users(id,email,password_hash,name,created_at) VALUES(?,?,?,?,?)",id,address,hash,name,now).run();}
    catch(error){if(String(error.message).includes("UNIQUE"))fail(409,"An account with this email already exists. Try signing in.","email");throw error;}
    return signIn(request,db,{id,email:address,name});
  }
  const user=await stmt(db,"SELECT id,email,name,password_hash FROM users WHERE email=?",address).first();
  if(!await verifyPassword(values.password,user?.password_hash))fail(401,"The email or password is incorrect.");
  return signIn(request,db,user);
}
function listingInput(values,user) {
  const type=text(values.property_type,"property_type",1,20);
  if(!["house","townhouse","apartment"].includes(type))fail(400,"Choose a house, townhouse, or apartment.","property_type");
  return {
    title:text(values.title,"title",5,120),description:text(values.description,"description",20,8000),property_type:type,
    address:text(values.address,"address",3,200),city:text(values.city,"city",2,100),postal_code:text(values.postal_code || "","postal_code",0,20),
    neighborhood:text(values.neighborhood || "","neighborhood",0,100),price:number(values.price,"price",1000,100000000),
    bedrooms:number(values.bedrooms,"bedrooms",0,30),bathrooms:number(values.bathrooms,"bathrooms",0,30,.5),
    area_sqft:number(values.area_sqft,"area_sqft",100,100000,.1),year_built:number(values.year_built,"year_built",1600,new Date().getUTCFullYear()+1),
    garage:number(values.garage ?? 0,"garage",0,20),quality:number(values.quality ?? 3,"quality",1,5),
    contact_name:text(values.contact_name || user.name,"contact_name",1,120),contact_email:email(values.contact_email || user.email,"contact_email"),
    contact_phone:text(values.contact_phone || "","contact_phone",0,40),
  };
}
async function ownedListing(db,id,user) {
  const listing=await stmt(db,"SELECT * FROM listings WHERE id=? AND seller_id=?",id,user.id).first();
  if(!listing)fail(404,"Listing not found.");return listing;
}
async function browse(request,db) {
  const q=new URL(request.url).searchParams,clauses=["l.status='active'"],params=[];
  const search=(q.get("q") || "").trim().slice(0,120);
  if(search){clauses.push("(l.title LIKE ? OR l.city LIKE ? OR l.neighborhood LIKE ? OR l.address LIKE ?)");params.push(...Array(4).fill("%"+search+"%"));}
  if(["house","townhouse","apartment"].includes(q.get("type"))){clauses.push("l.property_type=?");params.push(q.get("type"));}
  for(const[key,column]of[["max_price","price"],["min_beds","bedrooms"]]) {
    const raw=q.get(key);if(raw){const value=Number(raw);if(!Number.isFinite(value)||value<0)fail(400,"Choose valid search filters.");clauses.push(`l.${column}${key==="max_price"?"<=":">="}?`);params.push(value);}
  }
  const sort={newest:"l.created_at DESC,l.id DESC",price_asc:"l.price ASC,l.id ASC",price_desc:"l.price DESC,l.id ASC"}[q.get("sort")] || "l.created_at DESC,l.id DESC";
  const page=Number(q.get("page") || 1);if(!Number.isInteger(page)||page<1||page>1000)fail(400,"Invalid results page.");
  const where=clauses.join(" AND ");
  const listings=await rows(stmt(db,`SELECT ${PUBLIC_COLUMNS} FROM listings l WHERE ${where} ORDER BY ${sort} LIMIT 12 OFFSET ?`,...params,(page-1)*12));
  const total=await stmt(db,`SELECT count(*) AS total FROM listings l WHERE ${where}`,...params).first();
  return json({listings,total:total.total,page,page_size:12});
}
async function listingDetail(request,db,id) {
  const user=await currentUser(request,db);
  const listing=await stmt(db,`SELECT ${PUBLIC_COLUMNS},l.seller_id,l.contact_email,l.contact_phone FROM listings l WHERE l.id=?`,id).first();
  if(!listing || (listing.status!=="active" && listing.seller_id!==user?.id))fail(404,"Listing not found.");
  listing.is_owner=listing.seller_id===user?.id;delete listing.seller_id;
  if(!user){delete listing.contact_email;delete listing.contact_phone;}
  return json({listing});
}
async function saveListing(request,db,id) {
  const user=await requireUser(request,db),isNew=!id;if(id)await ownedListing(db,id,user);
  const data=listingInput(await body(request),user),now=Date.now(),columns=Object.keys(data),values=Object.values(data);
  if(id)await stmt(db,`UPDATE listings SET ${columns.map(c=>c+"=?").join(",")},updated_at=? WHERE id=? AND seller_id=?`,...values,now,id,user.id).run();
  else{id=crypto.randomUUID();await stmt(db,`INSERT INTO listings(id,seller_id,${columns.join(",")},status,created_at,updated_at) VALUES(${Array(columns.length+5).fill("?").join(",")})`,id,user.id,...values,"active",now,now).run();}
  return json({listing:await ownedListing(db,id,user)},isNew?201:200);
}
function imageType(bytes) {
  if(bytes[0]===255&&bytes[1]===216&&bytes[2]===255)return "image/jpeg";
  if(bytes[0]===137&&bytes[1]===80&&bytes[2]===78&&bytes[3]===71&&bytes[4]===13&&bytes[5]===10&&bytes[6]===26&&bytes[7]===10)return "image/png";
  if(String.fromCharCode(...bytes.slice(0,4))==="RIFF"&&String.fromCharCode(...bytes.slice(8,12))==="WEBP")return "image/webp";
  return null;
}
async function uploadPhoto(request,db,id) {
  const user=await requireUser(request,db);await ownedListing(db,id,user);
  if(Number(request.headers.get("content-length"))>MAX_PHOTO)fail(413,"The resized photo must be smaller than 768 KB.");
  const bytes=new Uint8Array(await request.arrayBuffer());
  if(bytes.length>MAX_PHOTO||bytes.length<12)fail(413,"Choose a valid photo smaller than 768 KB.");
  const type=imageType(bytes);if(!type||type!==request.headers.get("content-type"))fail(415,"Choose a JPEG, PNG, or WebP photo.");
  const photoId=crypto.randomUUID();
  await stmt(db,`INSERT INTO listing_photos(id,listing_id,content_type,data,byte_length,created_at) VALUES(?,?,?,?,?,?)
    ON CONFLICT(listing_id) DO UPDATE SET id=excluded.id,content_type=excluded.content_type,data=excluded.data,byte_length=excluded.byte_length,created_at=excluded.created_at`,
    photoId,id,type,bytes.buffer,bytes.length,Date.now()).run();return json({photo_id:photoId});
}
async function readPhoto(request,db,id) {
  const record=await stmt(db,`SELECT p.data,p.content_type,l.status,l.seller_id FROM listing_photos p JOIN listings l ON l.id=p.listing_id WHERE p.id=?`,id).first();
  if(!record)fail(404,"Photo not found.");
  if(record.status!=="active"){const user=await currentUser(request,db);if(record.seller_id!==user?.id)fail(404,"Photo not found.");}
  const data=record.data instanceof ArrayBuffer?record.data:new Uint8Array(record.data);
  return new Response(data,{headers:{"Content-Type":record.content_type,"Cache-Control":"private, max-age=300","X-Content-Type-Options":"nosniff"}});
}
async function participant(db,id,user) {
  const conversation=await stmt(db,"SELECT * FROM conversations WHERE id=? AND (buyer_id=? OR seller_id=?)",id,user.id,user.id).first();
  if(!conversation)fail(404,"Conversation not found.");return conversation;
}
async function addMessage(db,conversation,user,message) {
  const value=text(message,"message",1,4000),now=Date.now(),readColumn=conversation.buyer_id===user.id?"buyer_read_at":"seller_read_at";
  await db.batch([
    stmt(db,"INSERT INTO messages(id,conversation_id,sender_id,body,created_at) VALUES(?,?,?,?,?)",crypto.randomUUID(),conversation.id,user.id,value,now),
    stmt(db,`UPDATE conversations SET updated_at=?,${readColumn}=? WHERE id=?`,now,now,conversation.id),
  ]);
}
async function contactSeller(request,db) {
  const user=await requireUser(request,db),values=await body(request,12000);
  const listing=await stmt(db,"SELECT id,seller_id,status FROM listings WHERE id=?",values.listing_id).first();
  if(!listing||listing.status!=="active")fail(404,"This listing is no longer available.");
  if(listing.seller_id===user.id)fail(400,"This is your own listing.");
  text(values.message,"message",1,4000);await rateLimit(db,"messages:"+user.id,30,60000);
  const now=Date.now();
  await stmt(db,`INSERT INTO conversations(id,listing_id,buyer_id,seller_id,buyer_read_at,seller_read_at,created_at,updated_at)
    VALUES(?,?,?,?,0,0,?,?) ON CONFLICT(listing_id,buyer_id) DO NOTHING`,crypto.randomUUID(),listing.id,user.id,listing.seller_id,now,now).run();
  const conversation=await stmt(db,"SELECT * FROM conversations WHERE listing_id=? AND buyer_id=?",listing.id,user.id).first();
  await addMessage(db,conversation,user,values.message);return json({conversation_id:conversation.id},201);
}
async function inbox(request,db) {
  const user=await requireUser(request,db);
  const conversations=await rows(stmt(db,`SELECT c.id,c.listing_id,c.updated_at,l.title,l.price,l.status AS listing_status,
    CASE WHEN c.buyer_id=? THEN l.contact_name ELSE b.name END AS other_name,
    CASE WHEN c.buyer_id=? THEN l.contact_email ELSE b.email END AS other_email,
    CASE WHEN c.buyer_id=? THEN 'buyer' ELSE 'seller' END AS role,
    (SELECT body FROM messages m WHERE m.conversation_id=c.id ORDER BY created_at DESC,id DESC LIMIT 1) AS last_message,
    (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id AND m.sender_id<>? AND m.created_at>CASE WHEN c.buyer_id=? THEN c.buyer_read_at ELSE c.seller_read_at END) AS unread
    FROM conversations c JOIN listings l ON l.id=c.listing_id JOIN users b ON b.id=c.buyer_id WHERE c.buyer_id=? OR c.seller_id=? ORDER BY c.updated_at DESC,c.id DESC`,user.id,user.id,user.id,user.id,user.id,user.id,user.id));
  return json({conversations});
}
async function conversationDetail(request,db,id) {
  const user=await requireUser(request,db);await participant(db,id,user);
  return json({messages:await rows(stmt(db,"SELECT * FROM (SELECT id,sender_id,body,created_at FROM messages WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT 500) ORDER BY created_at ASC,id ASC",id))});
}

export async function handleApi(request,db) {
  try {
    if(!db)fail(503,"The database is not ready. Please try again shortly.");
    const method=request.method,path=new URL(request.url).pathname;
    if(!["GET","HEAD","OPTIONS"].includes(method)) {
      const origin=request.headers.get("origin"),site=request.headers.get("sec-fetch-site");
      if((origin&&origin!==new URL(request.url).origin)||site==="cross-site")fail(403,"Please submit this action from Ownly.");
    }
    if(path==="/api/session"&&method==="GET")return json({user:await currentUser(request,db)});
    if(path==="/api/register"&&method==="POST")return await authenticate(request,db,true);
    if(path==="/api/login"&&method==="POST")return await authenticate(request,db,false);
    if(path==="/api/logout"&&method==="POST") {
      const token=cookieToken(request);if(token)await stmt(db,"DELETE FROM sessions WHERE token_hash=?",await digest(token)).run();
      return json({ok:true},200,{"Set-Cookie":cookie(request,"",0)});
    }
    if(path==="/api/listings"&&method==="GET")return await browse(request,db);
    if(path==="/api/listings"&&method==="POST")return await saveListing(request,db);
    if(path==="/api/me/listings"&&method==="GET") {
      const user=await requireUser(request,db);
      return json({listings:await rows(stmt(db,`SELECT ${PUBLIC_COLUMNS},l.contact_email,l.contact_phone FROM listings l WHERE l.seller_id=? AND l.status<>'archived' ORDER BY l.updated_at DESC`,user.id))});
    }
    const listingMatch=path.match(LISTING_PATH);
    if(listingMatch) {
      const[,id,suffix]=listingMatch;
      if(suffix==="/photo"&&method==="PUT")return await uploadPhoto(request,db,id);
      if(!suffix&&method==="GET")return await listingDetail(request,db,id);
      if(!suffix&&method==="PUT")return await saveListing(request,db,id);
      if(!suffix&&(method==="PATCH"||method==="DELETE")) {
        const user=await requireUser(request,db);await ownedListing(db,id,user);
        const status=method==="DELETE"?"archived":(await body(request)).status;
        if(!["active","sold","archived"].includes(status))fail(400,"Choose an available listing status.");
        await stmt(db,"UPDATE listings SET status=?,updated_at=? WHERE id=? AND seller_id=?",status,Date.now(),id,user.id).run();return json({ok:true});
      }
    }
    const photoMatch=path.match(PHOTO_PATH);if(photoMatch&&method==="GET")return await readPhoto(request,db,photoMatch[1]);
    if(path==="/api/conversations"&&method==="POST")return await contactSeller(request,db);
    if(path==="/api/conversations"&&method==="GET")return await inbox(request,db);
    const conversationMatch=path.match(CONVERSATION_PATH);
    if(conversationMatch) {
      const[,id,suffix]=conversationMatch;
      if(!suffix&&method==="GET")return await conversationDetail(request,db,id);
      if(suffix==="/messages"&&method==="POST") {
        const user=await requireUser(request,db),conversation=await participant(db,id,user),values=await body(request,12000);
        await rateLimit(db,"messages:"+user.id,30,60000);await addMessage(db,conversation,user,values.message);return json({ok:true},201);
      }
      if(suffix==="/read"&&method==="POST") {
        const user=await requireUser(request,db),conversation=await participant(db,id,user),column=conversation.buyer_id===user.id?"buyer_read_at":"seller_read_at";
        await stmt(db,`UPDATE conversations SET ${column}=? WHERE id=?`,Date.now(),id).run();return json({ok:true});
      }
    }
    fail(404,"This page could not be found.");
  } catch(error) {
    if(error instanceof HttpError)return json({error:error.message,field:error.field},error.status);
    // Never log request bodies, passwords, cookies, or SQL-bound personal data.
    console.error("Ownly API request failed",error?.name || "Error");
    return json({error:"Something went wrong. Please try again."},500);
  }
}
