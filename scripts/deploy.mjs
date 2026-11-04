// Stage-three administrative tool. NOT run against production in phase two.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID, createHash } from 'node:crypto';
import { readJson, TERMINAL } from '../lib/storage.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const [command,...args]=process.argv.slice(2);
function option(key) { const i=args.indexOf('--'+key); if(i<0 || !args[i+1]) throw new Error('缺少 --'+key); return path.resolve(args[i+1]); }
try {
  if(!args.includes('--confirm-install')) throw new Error('需要明确的阶段三安装确认：--confirm-install；本工具不会启用真实执行');
  const target=option('destination');
  if(path.basename(target)!=='maa-controller') throw new Error('安装目录名必须为 maa-controller');
  if(fs.existsSync(target) && fs.lstatSync(target).isSymbolicLink()) throw new Error('不操作链接目录');
  const data=option('data');
  const active=readJson(path.join(data,'runtime','active.json'));
  const state=active?readJson(path.join(data,'runtime','runs',active.id,'state.json')):null;
  if(active && (!state || !TERMINAL.has(state.status) || !state.safeToRelease)) throw new Error('活动任务或未知状态未核清，禁止安装/回滚');
  const backup=path.join(path.dirname(target),'_maa-controller-backup-'+randomUUID());
  if(command==='install') {
    const source=args.includes('--source')?option('source'):path.join(root,'dist','maa-controller');
    const manifest=readJson(path.join(source,'manifest.json'));
    if(!manifest) throw new Error('请先构建安装包');
    const stage=path.join(path.dirname(target),'_maa-controller-stage-'+randomUUID());
    fs.mkdirSync(stage,{recursive:true});
    for(const [name,hash] of Object.entries(manifest.files)) {
      const from=path.resolve(source,name), to=path.resolve(stage,name);
      if(!from.startsWith(source+path.sep) || !to.startsWith(stage+path.sep)) throw new Error('安装清单路径越界');
      const bytes=fs.readFileSync(from);
      if(createHash('sha256').update(bytes).digest('hex')!==hash) throw new Error('安装包校验失败');
      fs.mkdirSync(path.dirname(to),{recursive:true});
      fs.writeFileSync(to,bytes);
    }
    if(fs.existsSync(target)) fs.renameSync(target,backup);
    try { fs.renameSync(stage,target); }
    catch(e) { if(fs.existsSync(backup)) fs.renameSync(backup,target); throw e; }
    console.log('已安装默认停用的模块：'+target);
    if(fs.existsSync(backup)) console.log('备份：'+backup);
  } else if(command==='rollback') {
    const previous=option('backup');
    if(path.dirname(previous)!==path.dirname(target) || !path.basename(previous).startsWith('_maa-controller-backup-') || !fs.lstatSync(previous).isDirectory() || fs.lstatSync(previous).isSymbolicLink()) throw new Error('备份必须是同目录下的本模块备份');
    if(fs.existsSync(target)) fs.renameSync(target,backup);
    try { fs.renameSync(previous,target); }
    catch(e) { if(fs.existsSync(backup)) fs.renameSync(backup,target); throw e; }
    console.log('已恢复模块文件；本模块数据目录保留。替换前版本：'+backup);
  } else throw new Error('仅支持 install / rollback');
} catch(e) { console.error(e.message); process.exitCode=1; }
