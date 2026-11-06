import path from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import { Controller } from '../lib/controller.mjs';
import { readJson, atomicJson } from '../lib/storage.mjs';
import { fixture, origin, terminal, until, cleanActive } from './helpers.mjs';

test('模拟整条链路：并发请求只启动一份，完成后核对统计并持久去重通知',async t=>{
  const f=fixture(), c=f.controller;
  t.after(()=>cleanActive(c));
  const results=await Promise.all(Array.from({length:8},()=>c.start(origin)));
  assert.equal(results.filter(x=>x.code==='accepted').length,1);
  const s=await terminal(c);
  assert.equal(s.status,'success');
  assert.equal(s.stats.drops['30012'].quantity,12);
  assert.equal(s.stats.battles,12);
  const reloaded=new Controller(f.options), sent=[];
  await reloaded.notify(async(chat,text)=>{sent.push({chat,text});return {message_id:sent.length};},()=>true);
  await new Controller(f.options).notify(async()=>{throw Error('不应重发');},()=>true);
  assert.equal(sent.length,2);
  assert.ok(sent.every(x=>x.chat===origin.chatId));
  assert.match(sent[0].text,/实际开始/);
  assert.match(sent[1].text,/预设执行完成/);
  assert.match(sent[1].text,/固源岩 × 12/);
});
test('任务错误后队列完成仍为部分完成，连接失败不得发送开始通知',async t=>{
  for(const [scenario,status] of [['partial','partial'],['connect_fail','failed']]) {
    const f=fixture(scenario), c=f.controller;
    t.after(()=>cleanActive(c));
    await c.start(origin);
    const s=await terminal(c);
    assert.equal(s.status,status);
    const sent=[];
    await c.notify(async(_,text)=>{sent.push(text);return true;},()=>true);
    assert.equal(sent.length,scenario==='connect_fail'?1:2);
  }
});
test('证据缺失报告未知并保留锁，不能自动重跑',async t=>{
  const c=fixture('unknown').controller; t.after(()=>cleanActive(c));
  await c.start(origin);
  assert.equal((await terminal(c)).status,'unknown');
  assert.equal((await c.start(origin)).code,'busy');
});
test('宿主对象丢失后任务继续；恢复对象查询和温和停止，不建立第二份',async t=>{
  const f=fixture('hang'); t.after(()=>cleanActive(f.controller));
  await f.controller.start(origin);
  await until(()=>f.controller.active()?.startedAt);
  const c=new Controller(f.options);
  assert.equal((await c.start(origin)).code,'busy');
  assert.equal((await c.control('status',origin)).state.status,'running');
  await c.control('stop',origin);
  assert.equal((await terminal(c)).status,'cancelled');
});
test('温和停止不自动升级；明确强制只终止已归属的模拟执行器',async t=>{
  const f=fixture('stop_delayed'),c=f.controller;t.after(()=>cleanActive(c));
  await c.start(origin); await until(()=>c.active()?.startedAt);
  await c.control('stop',origin);
  await until(()=>c.active()?.status==='stopping');
  await new Promise(r=>setTimeout(r,250));
  assert.equal(c.active().status,'stopping');
  assert.equal((await c.control('force',origin)).ok,true);
  assert.equal(c.active().status,'cancelled');
  assert.equal(c.active().emulatorClosed,true);
});
test('通知失败保持待发，恢复后补发；任务结果独立于通知成败',async t=>{
  const f=fixture(),c=f.controller;t.after(()=>cleanActive(c));
  await c.start(origin); await terminal(c);
  await c.notify(async()=>null,()=>true);
  assert.equal(c.active().status,'success');
  const sent=[];
  const recovered=new Controller(f.options);
  await recovered.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  assert.equal(sent.length,0); // Known failed sends back off.
  recovered.now=()=>Date.now()+31000;
  await recovered.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  assert.equal(sent.length,2);
});
test('真实模式未启用时，在运行任何探测/模拟器命令前拒绝',async()=>{
  const f=fixture(),cfg=readJson(f.configFile);
  cfg.mode='real';cfg.realEnabled=false;atomicJson(f.configFile,cfg);
  let called=false;f.controller.helper=async()=>{called=true;throw Error('不得调用');};
  await assert.rejects(f.controller.start(origin),/真实执行尚未启用/);
  assert.equal(called,false);
});
test('GUI 阻塞只提出许可，目标变化不能关闭或启动',async()=>{
  const f=fixture('success',{guiBusy:true}),c=f.controller;
  const pending=await c.start(origin);
  assert.equal(pending.code,'gui_busy'); assert.equal(c.active(),null);
  await assert.rejects(c.start(origin,{...pending.target,pid:99},pending.planDigest),/身份已变化/);
  assert.equal(c.active(),null);
});
test('执行器异常退出为未知，不能用进程消失冒充成功',async t=>{
  const f=fixture('crash'),c=f.controller;t.after(()=>cleanActive(c));
  await c.start(origin);
  const s=await terminal(c);
  assert.equal(s.status,'unknown');
  assert.equal(s.safeToRelease,false);
});

test('停止超时只发一次需处理通知，原执行器继续等待，不自动强杀',async t=>{
  const f=fixture('stop_delayed'),c=f.controller;t.after(()=>cleanActive(c));
  const cfg=readJson(f.configFile);cfg.stopTimeoutSeconds=1;atomicJson(f.configFile,cfg);
  await c.start(origin);await until(()=>c.active()?.startedAt);
  await c.control('stop',origin);
  await until(()=>c.active()?.attention);
  const sent=[];
  await c.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  await c.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  assert.equal(sent.filter(x=>x.includes('需要处理')).length,1);
  assert.equal(c.active().status,'stopping');
  await c.control('force',origin);
});
test('未知任务明确清理后允许新请求，但原结果不能改写为成功',async t=>{
  const f=fixture('unknown'),c=f.controller;t.after(()=>cleanActive(c));
  await c.start(origin);const previous=await terminal(c);
  await new Promise(r=>setTimeout(r,150));
  const clean=await c.control('force',origin);
  assert.equal(clean.ok,true);
  assert.equal(c.active().status,'unknown');
  assert.equal(c.active().safeToRelease,true);
  const cfg=readJson(f.configFile);cfg.mock.scenario='success';atomicJson(f.configFile,cfg);
  const next=await c.start({...origin,messageId:'next'});
  assert.equal(next.code,'accepted');assert.notEqual(next.runId,previous.id);
  await terminal(c);
});


test('模拟宿主进程真正退出后，detached worker 继续执行并由新控制器接管',async t=>{
  const f=fixture('success',{stepSeconds:.4}),c=f.controller;t.after(()=>cleanActive(c));
  const {execFileSync}=await import('node:child_process');
  const {pathToFileURL}=await import('node:url');
  const moduleUrl=pathToFileURL(path.resolve('lib/controller.mjs')).href;
  const code='import {Controller} from '+JSON.stringify(moduleUrl)+'; const c=new Controller('+JSON.stringify(f.options)+'); console.log(JSON.stringify(await c.start('+JSON.stringify(origin)+')));';
  const output=execFileSync(process.execPath,['--input-type=module','-e',code],{encoding:'utf8',windowsHide:true});
  assert.equal(JSON.parse(output.trim()).code,'accepted');
  const parentExitedAt=Date.now();
  const recovered=new Controller(f.options);
  const state=await terminal(recovered);
  assert.equal(state.status,'success');
  assert.ok(state.finishedAt>parentExitedAt);
});

test('不同需处理事件分别去重，任务错误后仍能收到停止超时提醒',async t=>{
  const f=fixture('hang'),c=f.controller;t.after(()=>cleanActive(c));
  await c.start(origin);await until(()=>c.active()?.startedAt);
  const file=path.join(c.jobPath(c.active().id),'state.json');
  let s=readJson(file);s.attention='某步骤失败';s.attentionKey='task-error';atomicJson(file,s);
  const sent=[];
  await c.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  s=readJson(file);s.attention='温和停止超时';s.attentionKey='stop-timeout';atomicJson(file,s);
  await c.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  await c.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  assert.equal(sent.filter(x=>x.includes('需要处理')).length,2);
  await c.control('force',origin);
});


test('唤醒失败立即停止依赖步骤，记录失败而非用户取消，不自动重跑',async t=>{
  const f=fixture('startup_fail'),c=f.controller;t.after(()=>cleanActive(c));
  const result=await c.start(origin),s=await terminal(c);
  assert.equal(s.id,result.runId);
  assert.equal(s.status,'failed');
  assert.equal(s.tasks.StartUp,'error');
  assert.ok(Object.entries(s.tasks).filter(([k])=>k!=='StartUp').every(([,v])=>v!=='completed'));
  assert.match(s.reason,/开始唤醒失败/);
});

test('Python 首次运行不写入模块目录缓存，避免触发宿主意外重载',async t=>{
  const fs=await import('node:fs');
  const f=fixture(), source=path.dirname(f.options.worker), workerDir=path.join(f.root,'module','worker');
  fs.mkdirSync(workerDir,{recursive:true});
  for(const name of fs.readdirSync(source)) if(name.endsWith('.py')) fs.copyFileSync(path.join(source,name),path.join(workerDir,name));
  const c=new Controller({...f.options,worker:path.join(workerDir,'worker.py')});
  t.after(()=>cleanActive(c));
  assert.equal((await c.start(origin)).code,'accepted');
  assert.equal((await terminal(c)).status,'success');
  assert.equal(fs.existsSync(path.join(workerDir,'__pycache__')),false,'辅助器和后台执行器均不得改动模块文件树');
});

test('强制终止收尾期间不把执行器退出误报未知，恢复对象同样等待最终结果',async t=>{
  const fs=await import('node:fs'), {execFile}=await import('node:child_process'), {promisify}=await import('node:util');
  const exec=promisify(execFile), f=fixture('hang'), c=f.controller;
  t.after(()=>cleanActive(c));
  await c.start(origin); await until(()=>c.active()?.startedAt);
  const s=c.active(), dir=c.jobPath(s.id), paused=path.join(dir,'test-force-paused');
  const python=String.raw`import sys,json,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import worker
file=Path(sys.argv[2])
job=worker.validate_job(worker.read_json(file))
original=worker.write_json
def delayed_write(path,value):
    if Path(path).name=='state.json':
        (Path(path).parent/'test-force-paused').touch()
        time.sleep(1)
    original(path,value)
worker.write_json=delayed_write
print(json.dumps(worker.force(job,file.parent)))`;
  c.helper=async(command,jobFile)=>{
    assert.equal(command,'force');
    const result=await exec(f.options.python,['-B','-c',python,path.dirname(f.options.worker),jobFile],{windowsHide:true,timeout:10000});
    return JSON.parse(result.stdout.trim());
  };
  const forcing=c.control('force',origin), sent=[];
  try {
    await until(()=>fs.existsSync(paused));
    const reloaded=new Controller(f.options);
    assert.notEqual(reloaded.active().status,'unknown','强制收尾仍在进行，不能当作异常退出');
    await reloaded.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
    assert.equal(sent.some(text=>/最终状态未知|本次任务已取消/.test(text)),false);
  } finally { await forcing; }
  const reloaded=new Controller(f.options);
  assert.equal(reloaded.active().status,'cancelled');
  await reloaded.notify(async(_,text)=>{sent.push(text);return 1;},()=>true);
  assert.equal(sent.filter(text=>text.includes('本次任务已取消')).length,1);
});

test('已完成任务的明确强制请求进入清理，查询和其他会话不会触发',async()=>{
  const f=fixture(),c=f.controller,id='00000000-0000-0000-0000-000000000000';
  const dir=c.jobPath(id),state={id,mode:'mock',origin,status:'success',safeToRelease:true,finishedAt:123,tasks:{Fight:'completed'},stats:{battles:30},warnings:[]};
  atomicJson(path.join(dir,'state.json'),state);
  atomicJson(path.join(c.root,'active.json'),{id});
  const calls=[];
  c.helper=async(command,file)=>{calls.push({command,file});return {ok:true,message:'绑定模拟器已关闭；原任务结果保持不变'};};
  assert.equal((await c.control('status',origin)).state.status,'success');
  assert.equal(calls.length,0);
  await assert.rejects(c.control('force',{...origin,userId:'other'}),/不属于/);
  assert.equal(calls.length,0);
  const result=await c.control('force',origin);
  assert.equal(result.ok,true);
  assert.deepEqual(calls,[{command:'force',file:path.join(dir,'job.json')}]);
  assert.deepEqual(c.active(),state);
});

test('结果展示区分条件检测和错误，清理信息不覆盖原成功状态或统计',async()=>{
  const {formatState}=await import('../lib/controller.mjs');
  const state={status:'success',stats:{battles:30},subtaskDiagnostics:[{kind:'condition',label:'信用不足提示',count:6}],warnings:['基建子步骤报告错误：UnknownTask'],cleanup:{ok:true,at:1}};
  const text=formatState(state);
  assert.match(text,/预设执行完成/);
  assert.match(text,/条件检测未命中/);
  assert.match(text,/信用不足提示.*6/);
  assert.match(text,/UnknownTask/);
  assert.match(text,/绑定模拟器已关闭/);
  assert.doesNotMatch(text,/统计不完整|任务已取消/);
  assert.match(formatState({...state,cleanup:{ok:false,reason:'实例被占用',at:2}}),/关闭未确认.*实例被占用/);
});

test('售罄跳过单独展示，保留其他真实子步骤告警',async()=>{
  const {formatState}=await import('../lib/controller.mjs');
  const text=formatState({status:'success',subtaskDiagnostics:[{kind:'skipped',label:'优先购买商品已售罄（招聘许可）',count:1}],warnings:['其他购物错误']});
  assert.match(text,/正常跳过：优先购买商品已售罄（招聘许可）/);
  assert.match(text,/其他购物错误/);
  assert.doesNotMatch(text,/信用子步骤报告错误：CreditShoppingTask/);
});
