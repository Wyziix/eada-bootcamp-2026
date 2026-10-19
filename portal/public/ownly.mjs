const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(n);
const num = n => new Intl.NumberFormat('en-US').format(n);
const date = n => new Date(n).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
const typeName = t => ({house:'House',townhouse:'Townhouse',apartment:'Apartment'}[t] || t);
const house = '<svg viewBox="0 0 80 70" fill="none" aria-hidden="true"><path d="M8 33 40 7l32 26M17 28v34h46V28M33 62V40h15v22M24 35h4m26 0h4" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const state = {user:null,view:'browse',page:1,authMode:'register',pending:null,conversations:[],thread:null,detail:null,remove:null};
let toastTimer, photoPreviewUrl;
async function api(path,options={}) {
  const headers = new Headers(options.headers);
  let body = options.body;
  if(body && !(body instanceof Blob)){headers.set('Content-Type','application/json');body=JSON.stringify(body);}
  const response = await fetch('/api'+path,{...options,headers,body,credentials:'same-origin'});
  const data = await response.json().catch(()=>({error:'The server could not complete this request.'}));
  if(!response.ok){const error=new Error(data.error);error.status=response.status;error.field=data.field;throw error;}
  return data;
}
function errorAt(id,error){$(id).textContent=error?.message || error || '';$(id).hidden=!error;}
function toast(message){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,4500);}
function busy(button,yes,label){button.disabled=yes;if(yes){button.dataset.label=button.innerHTML;button.textContent=label;}else if(button.dataset.label)button.innerHTML=button.dataset.label;}
function showDialog(id){if(!$(id).open)$(id).showModal();}
function closeDetail(){ state.detail=null;$('property-dialog').close(); const url=new URL(location.href);url.searchParams.delete('listing');history.replaceState(null,'',url); }
function updateAccount(){
  $('sign-in-button').hidden=!!state.user;$('join-button').hidden=!!state.user;
  $('account-name').hidden=!state.user;$('sign-out-button').hidden=!state.user;
  $('account-name').textContent=state.user?.name || '';
  $('account-name').title=state.user?.email || '';
  if(!state.user)$('unread-badge').hidden=true;
}
function renderAuth(){
  const register=state.authMode==='register';
  $('auth-title').textContent=register?'Make yourself at home.':'Good to have you back.';
  $('auth-description').textContent=register?'Create an account to list a property and talk to owners.':'Sign in to your listings and conversations.';
  $('auth-submit').textContent=register?'Create my account ↗':'Sign in ↗';
  $('auth-switch-label').textContent=register?'Already have an account?':'New to Ownly?';
  $('auth-switch').textContent=register?'Sign in':'Create an account';
  $('auth-password').autocomplete=register?'new-password':'current-password';errorAt('auth-error','');
}
function openAuth(mode='register',pending=null){state.authMode=mode;state.pending=pending;renderAuth();showDialog('auth-dialog');}
function requireAccount(action){if(state.user)return action();openAuth('register',action);}
$('sign-in-button').onclick=()=>openAuth('login');$('join-button').onclick=()=>openAuth();
$('auth-switch').onclick=()=>{state.authMode=state.authMode==='register'?'login':'register';renderAuth();};
$('auth-form').onsubmit=async event=>{
  event.preventDefault();const button=$('auth-submit');busy(button,true,state.authMode==='register'?'Creating account…':'Signing in…');errorAt('auth-error','');
  try{
    const {user}=await api('/'+state.authMode,{method:'POST',body:Object.fromEntries(new FormData(event.target))});
    state.user=user;updateAccount();$('auth-dialog').close();$('auth-password').value='';
    const pending=state.pending;state.pending=null;toast(state.authMode==='register'?'Welcome to Ownly. Make yourself at home.':'You’re signed in.');
    await refreshInbox(false);if(pending)await pending();else if(state.detail)await openProperty(state.detail);
  }catch(error){errorAt($('auth-dialog').open?'auth-error':'page-error',error);}finally{busy(button,false);}
};
$('sign-out-button').onclick=async()=>{
  try{await api('/logout',{method:'POST'});state.user=null;state.thread=null;state.conversations=[];state.pending=null;updateAccount();
    document.querySelectorAll('dialog[open]').forEach(d=>d.close());$('my-listings-grid').replaceChildren();$('conversation-list').replaceChildren();$('thread').replaceChildren();
    closeDetail();await navigate('browse');toast('You’re signed out.');
  }catch(error){errorAt('page-error',error);}
};
for(const button of document.querySelectorAll('[data-close]'))button.onclick=()=>button.dataset.close==='property-dialog'?closeDetail():$(button.dataset.close).close();
$('property-dialog').addEventListener('cancel',()=>{const url=new URL(location.href);url.searchParams.delete('listing');history.replaceState(null,'',url);});
async function navigate(view,updateHash=true){
  if(!['browse','my-listings','messages'].includes(view))view='browse';
  if(view!=='browse'&&!state.user)return openAuth('login',()=>navigate(view));
  state.view=view;errorAt('page-error','');
  for(const element of document.querySelectorAll('.view'))element.hidden=element.id!==view+'-view';
  for(const link of document.querySelectorAll('[data-view]'))link.classList.toggle('active',link.dataset.view===view);
  if(updateHash)history.replaceState(null,'','#'+view);
  try{if(view==='my-listings')await loadMyListings();if(view==='messages')await refreshInbox(true);}catch(error){errorAt('page-error',error);}
}
for(const link of document.querySelectorAll('[data-view]'))link.onclick=event=>{event.preventDefault();navigate(link.dataset.view);};
window.addEventListener('hashchange',()=>{const hash=location.hash.slice(1);if(hash==='signup'||hash==='login')openAuth(hash==='login'?'login':'register');else if(hash!=='homes')navigate(hash,false);});
function empty(title,description,action='List a property',attribute='data-create-listing'){
  return `<div class="empty-state"><div class="empty-icon">${house}</div><h3>${esc(title)}</h3><p>${esc(description)}</p><button class="button button-small" ${attribute}>${esc(action)} ↗</button></div>`;
}
function card(listing,owner=false){
  return `<article class="listing-card"><a href="?listing=${listing.id}" class="card-photo" data-property="${listing.id}" aria-label="View ${esc(listing.title)}">${listing.photo_id?`<img src="/api/photos/${listing.photo_id}" alt="${esc(listing.title)}" loading="lazy">`:`<div class="photo-placeholder">${house}<small>A new place to imagine.</small></div>`}<span class="type-pill">${esc(typeName(listing.property_type))}</span>${listing.status!=='active'?`<span class="status-pill">${esc(listing.status)}</span>`:''}</a><div class="card-body"><div class="card-price">${money(listing.price)} <small>USD</small></div><h3><a class="card-title" data-property="${listing.id}" href="?listing=${listing.id}">${esc(listing.title)}</a></h3><p class="card-address">${esc(listing.address)}, ${esc(listing.city)}</p><div class="card-facts"><span>${listing.bedrooms} beds</span><span>${listing.bathrooms} baths</span><span>${num(listing.area_sqft)} sq ft</span></div><div class="card-footer"><span>${esc(listing.contact_name)}</span><button class="text-button" data-property="${listing.id}">Take a look ↗</button></div>${owner?`<div class="owner-actions"><button data-edit="${listing.id}">Edit</button><button data-status="${listing.id}" data-next="${listing.status==='sold'?'active':'sold'}">${listing.status==='sold'?'Mark available':'Mark sold'}</button><button data-remove="${listing.id}">Remove</button></div>`:''}</div></article>`;
}
function bindCards(container){
  for(const button of container.querySelectorAll('[data-property]'))button.onclick=event=>{event.preventDefault();openProperty(button.dataset.property).catch(e=>errorAt('page-error',e));};
  for(const button of container.querySelectorAll('[data-create-listing]'))button.onclick=()=>requireAccount(()=>openEditor());
  for(const button of container.querySelectorAll('[data-clear-search]'))button.onclick=()=>{$('search-form').reset();state.page=1;loadListings();};
  for(const button of container.querySelectorAll('[data-edit]'))button.onclick=()=>editListing(button.dataset.edit);
  for(const button of container.querySelectorAll('[data-remove]'))button.onclick=()=>{state.remove=button.dataset.remove;showDialog('confirm-dialog');};
  for(const button of container.querySelectorAll('[data-status]'))button.onclick=async()=>{
    busy(button,true,'Saving…');try{await api('/listings/'+button.dataset.status,{method:'PATCH',body:{status:button.dataset.next}});await loadMyListings();await loadListings();toast('Listing updated.');}catch(e){errorAt('page-error',e);}finally{busy(button,false);}
  };
}
let browseRequest=0;
async function loadListings(){
  const generation=++browseRequest,query=new URLSearchParams(new FormData($('search-form')));query.set('page',state.page);query.set('sort',$('sort-listings').value);
  errorAt('page-error','');
  try{
    const result=await api('/listings?'+query);if(generation!==browseRequest)return;
    const filters=[...new FormData($('search-form')).values()].some(Boolean);
    $('result-count').textContent=`${result.total} ${result.total===1?'home':'homes'} ${filters?'match your search':'to discover'}`;
    $('listings-grid').innerHTML=result.listings.length?result.listings.map(l=>card(l)).join(''):filters?empty('A little more room to search.','Try another city or a wider price range.','Clear filters','data-clear-search'):empty('The next chapter starts with you.','Ownly is just getting started. Be the first to introduce a home.');
    bindCards($('listings-grid'));$('pagination').hidden=result.total<=12;$('page-label').textContent=`Page ${state.page} of ${Math.max(1,Math.ceil(result.total/12))}`;
    $('previous-page').disabled=state.page<=1;$('next-page').disabled=state.page*12>=result.total;
  }catch(e){$('result-count').textContent='Homes could not be loaded.';errorAt('page-error',e);}
}
$('search-form').onsubmit=event=>{event.preventDefault();state.page=1;loadListings();};
$('sort-listings').onchange=()=>{state.page=1;loadListings();};
$('previous-page').onclick=()=>{state.page--;loadListings();};$('next-page').onclick=()=>{state.page++;loadListings();};
async function loadMyListings(){
  const {listings}=await api('/me/listings');$('my-listings-grid').innerHTML=listings.length?listings.map(l=>card(l,true)).join(''):empty('Every home has a story.','Let’s tell yours. Create your first property listing.');bindCards($('my-listings-grid'));
}
function openEditor(listing){
  const form=$('listing-form');form.reset();errorAt('listing-error','');
  form.elements.id.value=listing?.id || '';
  for(const [key,value]of Object.entries(listing || {}))if(form.elements.namedItem(key))form.elements.namedItem(key).value=value;
  form.elements.contact_name.value=listing?.contact_name || state.user.name;form.elements.contact_email.value=listing?.contact_email || state.user.email;
  form.elements.year_built.max=new Date().getFullYear()+1;
  $('listing-dialog-title').textContent=listing?'A fresh look at your home.':'Make room for possibility.';
  $('publish-listing').textContent=listing?'Save my changes ↗':'Publish my listing ↗';
  if(photoPreviewUrl){URL.revokeObjectURL(photoPreviewUrl);photoPreviewUrl=null;}
  $('photo-preview').hidden=!listing?.photo_id;if(listing?.photo_id)$('photo-preview').src='/api/photos/'+listing.photo_id;
  showDialog('listing-dialog');
}
async function editListing(id){try{const {listing}=await api('/listings/'+id);closeDetail();openEditor(listing);}catch(e){errorAt('page-error',e);}}
for(const button of document.querySelectorAll('[data-create-listing]'))button.onclick=()=>requireAccount(()=>openEditor());
$('listing-photo').onchange=()=>{
  errorAt('listing-error','');const file=$('listing-photo').files[0];if(photoPreviewUrl)URL.revokeObjectURL(photoPreviewUrl);
  if(file){photoPreviewUrl=URL.createObjectURL(file);$('photo-preview').src=photoPreviewUrl;$('photo-preview').hidden=false;}
};
async function resizePhoto(file){
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Choose a JPEG, PNG, or WebP photo.');
  if(file.size>10*1024*1024)throw Error('Choose a photo smaller than 10 MB.');
  const image=await createImageBitmap(file).catch(()=>{throw Error('This photo could not be opened. Please choose another image.');});
  const canvas=document.createElement('canvas'),scale=Math.min(1,1600/Math.max(image.width,image.height));
  canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));
  canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);image.close();
  for(const quality of [.85,.7,.5,.3]){const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',quality));if(blob?.size<=768*1024)return blob;}
  throw Error('This photo is still too large. Try a smaller or simpler image.');
}
$('listing-form').onsubmit=async event=>{
  event.preventDefault();const form=event.target,button=$('publish-listing');busy(button,true,'Saving your home…');errorAt('listing-error','');
  try{
    const file=$('listing-photo').files[0],photo=file?await resizePhoto(file):null;
    const data=Object.fromEntries(new FormData(form)),id=data.id;delete data.id;
    for(const key of ['price','bedrooms','bathrooms','area_sqft','year_built','garage','quality'])data[key]=Number(data[key]);
    const {listing}=await api('/listings'+(id?'/'+id:''),{method:id?'PUT':'POST',body:data});
    form.elements.id.value=listing.id;
    if(photo){try{await api('/listings/'+listing.id+'/photo',{method:'PUT',body:photo,headers:{'Content-Type':photo.type}});}catch(e){throw Error('Your listing was saved, but the photo could not be uploaded. '+e.message+' Submit again to retry.');}}
    $('listing-dialog').close();await navigate('my-listings');await loadListings();toast(id?'Your listing has been updated.':'Your home is now listed on Ownly.');
  }catch(e){errorAt('listing-error',e);if(e.field)form.elements.namedItem(e.field)?.focus();}finally{busy(button,false);}
};
$('confirm-remove').onclick=async()=>{
  const button=$('confirm-remove');busy(button,true,'Removing…');try{await api('/listings/'+state.remove,{method:'DELETE'});$('confirm-dialog').close();await loadMyListings();await loadListings();toast('Listing removed. Your conversations are still in your inbox.');}catch(e){$('confirm-dialog').close();errorAt('page-error',e);}finally{busy(button,false);}
};
function estimateLink(listing){
  const query=new URLSearchParams({type:listing.property_type,area:listing.area_sqft,bedrooms:listing.bedrooms,bathrooms:Math.floor(listing.bathrooms),year:listing.year_built,garage:listing.garage,quality:listing.quality,neighborhood:listing.neighborhood});return '/estimate.html?'+query;
}
async function openProperty(id){
  const {listing:l}=await api('/listings/'+id);state.detail=id;
  const canEstimate=l.city.toLowerCase()==='ames'&&['house','townhouse'].includes(l.property_type)&&l.year_built<=2010;
  $('property-content').innerHTML=`<div class="property-cover">${l.photo_id?`<img src="/api/photos/${l.photo_id}" alt="${esc(l.title)}">`:`<div class="photo-placeholder">${house}<small>Imagine the possibilities.</small></div>`}</div><div class="property-info"><div class="property-overview"><span class="eyebrow">${esc(typeName(l.property_type))} · ${esc(l.status==='active'?'FOR SALE':l.status.toUpperCase())}</span><strong>${money(l.price)} <small>USD</small></strong></div><h2 id="property-title">${esc(l.title)}</h2><p class="property-address">${esc(l.address)}, ${esc(l.city)} ${esc(l.postal_code)}</p><div class="property-specs"><span><strong>${l.bedrooms}</strong> bedrooms</span><span><strong>${l.bathrooms}</strong> bathrooms</span><span><strong>${num(l.area_sqft)}</strong> sq ft</span><span><strong>${l.garage}</strong> garage spaces</span></div><div class="property-details"><div><h3>A little about this place.</h3><p class="property-description">${esc(l.description)}</p><dl class="property-meta"><dt>Built in</dt><dd>${l.year_built}</dd><dt>Neighborhood</dt><dd>${esc(l.neighborhood || 'Not specified')}</dd><dt>Finishes</dt><dd>${['Basic','Modest','Standard','High-end','Exceptional'][l.quality-1]}</dd></dl><div class="property-tools"><button class="button button-outline button-small" id="share-listing">Copy listing link ↗</button>${canEstimate?`<a class="button button-outline button-small" href="${esc(estimateLink(l))}" target="_blank" rel="noopener">Explore an estimate ↗</a>`:''}</div><p class="small-note">The asking price is set by the owner.${canEstimate?' Our valuation tool offers a separate, approximate current-year estimate.':''}</p></div><aside class="seller-contact"><p class="eyebrow">MEET THE OWNER</p><h3>${esc(l.contact_name)}</h3>${l.is_owner?'<p>This is your listing. Buyer messages will appear in your inbox.</p><button class="button" id="edit-detail">Edit my listing ↗</button>':!state.user?'<div class="contact-lock"><p>A good conversation starts with an introduction.</p><p>Join Ownly to view contact details and send the owner a message.</p><button class="button" id="contact-sign-in">Join to contact the owner ↗</button></div>':`<a class="contact-link" href="mailto:${esc(l.contact_email)}">${esc(l.contact_email)}</a>${l.contact_phone?`<a class="contact-link" href="tel:${esc(l.contact_phone.replace(/[^+0-9]/g,''))}">${esc(l.contact_phone)}</a>`:''}<form id="contact-form"><label for="contact-message">Send a message<textarea id="contact-message" rows="4" maxlength="4000" required placeholder="Hi, I’d love to learn more about this home…"></textarea></label><div class="inline-error" id="contact-error" role="alert" hidden></div><button class="button" id="send-contact">Message the owner ↗</button><p class="small-note">Delivered to the owner’s Ownly inbox. Your email is shared with the owner.</p></form>`}</aside></div></div>`;
  showDialog('property-dialog');const url=new URL(location.href);url.searchParams.set('listing',id);history.replaceState(null,'',url);
  $('share-listing').onclick=async()=>{try{await navigator.clipboard.writeText(location.origin+'/?listing='+id);toast('Listing link copied.');}catch{toast('You can copy this listing’s address from your browser.');}};
  if(l.is_owner)$('edit-detail').onclick=()=>editListing(id);
  else if(!state.user)$('contact-sign-in').onclick=()=>{$('property-dialog').close();openAuth('register',()=>openProperty(id));};
  else $('contact-form').onsubmit=async event=>{
    event.preventDefault();busy($('send-contact'),true,'Sending…');errorAt('contact-error','');
    try{const {conversation_id}=await api('/conversations',{method:'POST',body:{listing_id:id,message:$('contact-message').value}});closeDetail();state.thread=conversation_id;await navigate('messages');await openThread(conversation_id);toast('Your message has been sent.');}catch(e){errorAt('contact-error',e);}finally{if($('send-contact'))busy($('send-contact'),false);}
  };
}
function updateUnread(){const count=state.conversations.reduce((n,c)=>n+c.unread,0);$('unread-badge').hidden=!count;$('unread-badge').textContent=count>99?'99+':count;}
async function refreshInbox(render=true){
  if(!state.user)return;
  const {conversations}=await api('/conversations');state.conversations=conversations;updateUnread();
  if(!render)return;
  if(!state.thread && conversations.length)state.thread=conversations[0].id;
  $('conversation-list').innerHTML=conversations.length?conversations.map(c=>`<button class="conversation-button ${state.thread===c.id?'active':''}" data-conversation="${c.id}"><span class="conversation-person">${esc(c.other_name)} ${c.unread?`<span class="count-badge">${c.unread}</span>`:''}</span><strong>${esc(c.title)}</strong><span class="conversation-preview">${esc(c.last_message)}</span><span class="conversation-date">${esc(date(c.updated_at))} · ${c.role==='seller'?'Your listing':'Buying'}</span></button>`).join(''):'<div class="inbox-empty"><h3>Room for a conversation.</h3><p>Contact an owner from a listing, or wait for buyers to say hello.</p></div>';
  for(const b of $('conversation-list').querySelectorAll('[data-conversation]'))b.onclick=()=>openThread(b.dataset.conversation).catch(e=>errorAt('page-error',e));
  if(!conversations.length){state.thread=null;$('thread').innerHTML='<div class="empty-thread"><span>↔</span><h2>Your next conversation is out there.</h2><p>Explore homes and contact an owner to get started.</p><button class="button button-small" id="inbox-browse">Explore homes ↗</button></div>';$('inbox-browse').onclick=()=>navigate('browse');}
  else if(state.thread&&!$('reply-form'))await openThread(state.thread);
}
async function openThread(id){
  const c=state.conversations.find(c=>c.id===id);if(!c)return;
  const {messages}=await api('/conversations/'+id);state.thread=id;
  $('thread').innerHTML=`<div class="thread-heading"><div><h2>${esc(c.other_name)}</h2><p>${esc(c.title)} · ${esc(money(c.price))}</p><a href="mailto:${esc(c.other_email)}">${esc(c.other_email)}</a></div><span class="type-pill">${c.role==='seller'?'Interested buyer':'Property owner'}</span></div><div class="thread-messages" id="thread-messages">${messages.map(m=>`<div class="message ${m.sender_id===state.user.id?'own':''}"><p>${esc(m.body)}</p><time datetime="${new Date(m.created_at).toISOString()}">${esc(date(m.created_at))}</time></div>`).join('')}</div><form class="reply-form" id="reply-form"><label class="sr-only" for="reply-message">Your reply</label><textarea id="reply-message" placeholder="Keep the conversation going…" rows="2" required maxlength="4000"></textarea><button class="button" id="send-reply">Send reply ↗</button><div class="inline-error" id="reply-error" role="alert" hidden></div></form>`;
  $('thread-messages').scrollTop=$('thread-messages').scrollHeight;
  await api('/conversations/'+id+'/read',{method:'POST'});c.unread=0;updateUnread();
  for(const b of $('conversation-list').querySelectorAll('[data-conversation]')){b.classList.toggle('active',b.dataset.conversation===id);if(b.dataset.conversation===id)b.querySelector('.count-badge')?.remove();}
  $('reply-form').onsubmit=async event=>{event.preventDefault();const text=$('reply-message').value;busy($('send-reply'),true,'Sending…');errorAt('reply-error','');try{await api('/conversations/'+id+'/messages',{method:'POST',body:{message:text}});await openThread(id);await refreshInbox();}catch(e){errorAt('reply-error',e);}finally{busy($('send-reply'),false);}};
}
$('refresh-inbox').onclick=async()=>{try{const draft=$('reply-message')?.value;await refreshInbox();if(state.thread){await openThread(state.thread);if(draft&&$('reply-message'))$('reply-message').value=draft;}toast('Inbox refreshed.');}catch(e){errorAt('page-error',e);}};
async function init(){
  try{state.user=(await api('/session')).user;updateAccount();await loadListings();
    const hash=location.hash.slice(1);if(hash==='signup'||hash==='login')openAuth(hash==='login'?'login':'register');else if(['my-listings','messages'].includes(hash))await navigate(hash,false);
    const id=new URL(location.href).searchParams.get('listing');if(id)await openProperty(id);
    if(state.user)await refreshInbox(false);
  }catch(e){errorAt('page-error',e);}
  fetch('/assets/config.json').then(r=>r.json()).then(config=>{const neighborhoods=config.neighborhoods || [];const values=Array.isArray(neighborhoods)?neighborhoods:Object.keys(neighborhoods);$('neighborhood-options').innerHTML=values.map(n=>`<option value="${esc(typeof n==='object'?n.name || n.code:n)}"></option>`).join('');}).catch(()=>{});
}
init();
setInterval(()=>{if(state.user&&!document.hidden)refreshInbox(false).catch(()=>{});},30000);
