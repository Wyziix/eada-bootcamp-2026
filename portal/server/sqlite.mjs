import { DatabaseSync } from 'node:sqlite';
import { readdirSync, readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

export function openSqlite(filename, migrations=path.resolve(import.meta.dirname,'../drizzle')) {
  if(filename!==':memory:')mkdirSync(path.dirname(filename),{recursive:true});
  const native=new DatabaseSync(filename);
  native.exec('PRAGMA foreign_keys=ON; PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;');
  native.exec('CREATE TABLE IF NOT EXISTS ownly_migrations(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)');
  for(const name of readdirSync(migrations).filter(n=>n.endsWith('.sql')).sort()) {
    if(native.prepare('SELECT name FROM ownly_migrations WHERE name=?').get(name))continue;
    native.exec('BEGIN');
    try {native.exec(readFileSync(path.join(migrations,name),'utf8'));native.prepare('INSERT INTO ownly_migrations VALUES(?,?)').run(name,Date.now());native.exec('COMMIT');}
    catch(error){native.exec('ROLLBACK');throw error;}
  }
  const normalize=v=>v instanceof ArrayBuffer?new Uint8Array(v):v;
  function prepare(sql,values=[]) {
    return {sql,values,
      bind(...args){return prepare(sql,args.map(normalize));},
      async first(){return native.prepare(sql).get(...values) || null;},
      async all(){return {results:native.prepare(sql).all(...values)};},
      async run(){const r=native.prepare(sql).run(...values);return {success:true,meta:{changes:Number(r.changes)}};},
    };
  }
  return {prepare,
    async batch(statements){native.exec('BEGIN');try{const result=statements.map(s=>{const r=native.prepare(s.sql).run(...s.values);return {success:true,meta:{changes:Number(r.changes)}};});native.exec('COMMIT');return result;}catch(error){native.exec('ROLLBACK');throw error;}},
    close(){native.close();},native,
  };
}
