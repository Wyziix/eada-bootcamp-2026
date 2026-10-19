import http from 'node:http';
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {handleApi} from './server/api.mjs';
import {openSqlite} from './server/sqlite.mjs';

const root=path.resolve(import.meta.dirname,'public');
const db=openSqlite(process.env.OWNLY_DB_PATH || path.resolve(import.meta.dirname,'.data/ownly.sqlite'));
const types={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.mjs':'text/javascript','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.webp':'image/webp','.jpg':'image/jpeg'};
const port=Number(process.env.OWNLY_PORT || 8850);
const server=http.createServer(async(req,res)=>{
  try {
    const url=new URL(req.url,`http://${req.headers.host || "127.0.0.1:"+port}`);
    if(url.pathname.startsWith('/api/')) {
      const chunks=[];let size=0;
      for await(const chunk of req){size+=chunk.length;if(size>1024*1024){res.writeHead(413,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'The upload is too large.'}));return;}chunks.push(chunk);}
      const headers=new Headers();for(const[key,value]of Object.entries(req.headers))if(value)headers.set(key,Array.isArray(value)?value.join(','):value);
      headers.set('cf-connecting-ip',req.socket.remoteAddress || 'local');
      const request=new Request(url,{method:req.method,headers,...(!['GET','HEAD'].includes(req.method)?{body:Buffer.concat(chunks)}:{})});
      const response=await handleApi(request,db);
      res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));return;
    }
    let file;
    if(url.pathname==='/' || url.pathname==='/estimate.html')file=path.resolve(import.meta.dirname,url.pathname==='/'?'frontend/index.html':'frontend/estimate.html');
    else {file=path.resolve(root,'.'+decodeURIComponent(url.pathname));if(!file.startsWith(root+path.sep))throw Error('Invalid path');}
    const data=await readFile(file);
    res.writeHead(200,{'Content-Type':types[path.extname(file)] || 'application/octet-stream','Cache-Control':'no-cache','X-Content-Type-Options':'nosniff'});res.end(data);
  }catch{res.writeHead(404);res.end('Not found');}
});
server.listen(port,'127.0.0.1',()=>console.log(`Ownly: http://127.0.0.1:${port}`));
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>server.close(()=>{db.close();process.exit(0);}));
