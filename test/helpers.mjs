import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Controller } from '../lib/controller.mjs';
import { atomicJson, readJson, TERMINAL } from '../lib/storage.mjs';
export const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
export const python=path.join(project,'.venv','Scripts','python.exe');
export const owner='123456789';
export const origin={userId:owner,chatId:'private:'+owner,messageId:'1'};
export function message(text,id='1',patch={}) {
  const raw={post_type:'message',message_type:'private',time:Math.floor(Date.now()/1000),user_id:Number(owner),message_id:id,sender:{user_id:Number(owner)},message:[{type:'text',data:{text}}]};
  return {kind:'private',chatId:origin.chatId,userId:owner,messageId:id,text,raw,forwards:[],replyId:'',...patch};
}
export function fixture(scenario='success',extra={}) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'maa-offline-'));
  const c=readJson(path.join(project,'controller.example.json'));
  Object.assign(c,{mode:'mock',realEnabled:false,presetFile:path.join(project,'presets','daily.json')});
  c.mock={scenario,stepSeconds:.1,...extra};
  const configFile=path.join(root,'controller.json');
  atomicJson(configFile,c);
  const options={root:path.join(root,'runtime'),python,worker:path.join(project,'worker','worker.py'),configFile};
  return {root,configFile,options,controller:new Controller(options)};
}
export async function until(fn,timeout=10000) {
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline) { const value=await fn(); if(value) return value; await new Promise(r=>setTimeout(r,40)); }
  throw new Error('等待模拟状态超时');
}
export async function terminal(c) { return until(()=>{const s=c.active(); return s && TERMINAL.has(s.status)?s:false;}); }
export async function cleanActive(c) {
  const s=c.active();
  if(s && (!TERMINAL.has(s.status) || !s.safeToRelease)) {
    try { await c.control('force',origin); } catch {}
  }
}
