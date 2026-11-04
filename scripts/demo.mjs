import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Controller } from '../lib/controller.mjs';
import { atomicJson,readJson,TERMINAL } from '../lib/storage.mjs';
const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const root=path.join(project,'.runtime','demo',randomUUID());
const config=readJson(path.join(project,'controller.example.json'));
config.presetFile=path.join(project,'presets','daily.json');
config.mode='mock';config.realEnabled=false;
const file=path.join(root,'controller.json');atomicJson(file,config);
const c=new Controller({root:path.join(root,'runtime'),python:path.join(project,'.venv','Scripts','python.exe'),worker:path.join(project,'worker','worker.py'),configFile:file});
console.log('离线模拟：未连接 QQ、MAA 或 MuMu');
console.log((await c.start({userId:'offline-demo',chatId:'private:offline-demo',messageId:'demo'})).message);
while(true) {
  const s=c.active();
  await c.notify(async(_,text)=>{console.log(text);return true;},()=>true);
  if(s && TERMINAL.has(s.status)) break;
  await new Promise(r=>setTimeout(r,100));
}
console.log('运行账本：'+root);
