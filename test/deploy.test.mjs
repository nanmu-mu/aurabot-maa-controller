import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { project, fixture } from './helpers.mjs';
import { atomicJson } from '../lib/storage.mjs';

function sandbox() {
  const {root}=fixture();
  const source=path.join(root,'bundle');
  fs.mkdirSync(source);
  const bytes='export default {id:"maa-controller",defaults:{enabled:false}};\n';
  fs.writeFileSync(path.join(source,'index.js'),bytes);
  atomicJson(path.join(source,'manifest.json'),{files:{'index.js':createHash('sha256').update(bytes).digest('hex')}});
  return {root,source,dest:path.join(root,'modules','maa-controller'),data:path.join(root,'data')};
}
function run(s,command,args=[],confirm=true) {
  return execFileSync(process.execPath,[path.join(project,'scripts','deploy.mjs'),command,'--destination',s.dest,'--data',s.data,'--source',s.source,...(confirm?['--confirm-install']:[]),...args],{encoding:'utf8',windowsHide:true});
}
test('仅临时目录：首次安装默认停用、升级备份、回滚恢复',()=>{
  const s=sandbox();
  run(s,'install');
  const first=fs.readFileSync(path.join(s.dest,'index.js'),'utf8');
  fs.appendFileSync(path.join(s.dest,'index.js'),'// previous local version\n');
  const previous=fs.readFileSync(path.join(s.dest,'index.js'),'utf8');
  const log=run(s,'install'),backup=log.match(/备份：([^\r\n]+)/)?.[1];
  assert.ok(backup);
  assert.equal(fs.readFileSync(path.join(s.dest,'index.js'),'utf8'),first);
  run(s,'rollback',['--backup',backup]);
  assert.equal(fs.readFileSync(path.join(s.dest,'index.js'),'utf8'),previous);
});
test('无确认、活动任务、错误校验均拒绝，不能触碰其他模块',()=>{
  const s=sandbox();
  assert.throws(()=>run(s,'install',[],false));
  assert.equal(fs.existsSync(s.dest),false);
  const other=path.join(path.dirname(s.dest),'other');fs.mkdirSync(other,{recursive:true});
  fs.writeFileSync(path.join(other,'keep.txt'),'keep');
  const id='00000000-0000-0000-0000-000000000000';
  atomicJson(path.join(s.data,'runtime','active.json'),{id});
  atomicJson(path.join(s.data,'runtime','runs',id,'state.json'),{status:'unknown',safeToRelease:false});
  assert.throws(()=>run(s,'install'));
  assert.equal(fs.readFileSync(path.join(other,'keep.txt'),'utf8'),'keep');
  atomicJson(path.join(s.data,'runtime','runs',id,'state.json'),{status:'success',safeToRelease:true});
  fs.appendFileSync(path.join(s.source,'index.js'),'tampered');
  assert.throws(()=>run(s,'install'));
  assert.equal(fs.existsSync(s.dest),false);
});
test('回滚不能指向其他模块或其他父目录',()=>{
  const s=sandbox(); run(s,'install');
  assert.throws(()=>run(s,'rollback',['--backup',s.source]));
  assert.ok(fs.existsSync(path.join(s.dest,'index.js')));
});
