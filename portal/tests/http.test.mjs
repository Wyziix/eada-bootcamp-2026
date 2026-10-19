import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';

test('Node deployment accepts its HTTPS origin, sets Secure cookies and trusts only configured proxy IPs',async()=>{
  const reservation=net.createServer();await new Promise(r=>reservation.listen(0,'127.0.0.1',r));const port=reservation.address().port;await new Promise(r=>reservation.close(r));
  const folder=await mkdtemp(path.join(tmpdir(),'ownly-http-'));
  const child=spawn(process.execPath,['serve.mjs'],{cwd:path.resolve(import.meta.dirname,'..'),env:{...process.env,OWNLY_PORT:String(port),OWNLY_DB_PATH:path.join(folder,'ownly.sqlite'),OWNLY_PUBLIC_ORIGIN:'https://ownly.torras.ai',OWNLY_TRUST_PROXY:'1'},stdio:['ignore','pipe','pipe']});
  try{
    await new Promise((resolve,reject)=>{child.stdout.on('data',data=>{if(data.toString().includes('Ownly:'))resolve();});child.once('exit',code=>reject(Error('Server exited: '+code)));child.once('error',reject);});
    const base='http://127.0.0.1:'+port;
    assert.equal((await fetch(base+'/')).status,200);assert.match(await(await fetch(base+'/estimate.html')).text(),/Ownly/);
    assert.deepEqual(await(await fetch(base+'/healthz')).json(),{ok:true});
    const register=async(origin,ip,email)=>fetch(base+'/api/register',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json','X-Real-IP':ip,'CF-Connecting-IP':'9.9.9.9'},body:JSON.stringify({email,password:'Only a test password 2026!'})});
    assert.equal((await register('https://evil.test','192.0.2.1','a@example.test')).status,403);
    const account=await register('https://ownly.torras.ai','192.0.2.1','first@example.test');assert.equal(account.status,200);assert.match(account.headers.get('set-cookie'),/; Secure/);
    const cookie=account.headers.get('set-cookie').split(';')[0];assert.equal((await(await fetch(base+'/api/session',{headers:{Cookie:cookie}})).json()).user.email,'first@example.test');
    for(let i=0;i<11;i++)await fetch(base+'/api/login',{method:'POST',headers:{Origin:'https://ownly.torras.ai','Content-Type':'application/json','X-Real-IP':'192.0.2.1'},body:JSON.stringify({email:'first@example.test',password:'wrong password'})});
    assert.equal((await register('https://ownly.torras.ai','192.0.2.2','second@example.test')).status,200);
    const stored=new DatabaseSync(path.join(folder,'ownly.sqlite'),{readOnly:true});
    try{
      const limits=stored.prepare("SELECT key,hits FROM auth_limits WHERE key LIKE 'auth-ip:%'").all();
      const key=ip=>'auth-ip:'+createHash('sha256').update(ip).digest('hex');
      assert.equal(limits.length,2);assert.equal(limits.find(r=>r.key===key('192.0.2.1')).hits,12);assert.equal(limits.find(r=>r.key===key('192.0.2.2')).hits,1);
    }finally{stored.close();}
    assert.equal((await fetch(base+'/%2e%2e/server/api.mjs')).status,404);
  }finally{child.kill('SIGTERM');await new Promise(resolve=>child.once('close',resolve));await rm(folder,{recursive:true,force:true});}
});
