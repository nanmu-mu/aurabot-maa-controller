import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { setupAdapter } from '../lib/adapter.mjs';
import { readJson,atomicJson } from '../lib/storage.mjs';
import { fixture, message, owner, origin, project, python, until, terminal, cleanActive } from './helpers.mjs';

function host(f,enabled=true) {
  const hooks={},contexts=[],tools=[],timers=[],dispose=[],sent=[],asked=[];
  const api={dir:project,config:()=>({enabled:true,ownerLevel:'full',dryRun:false}),settings:()=>({enabled,pythonPath:python,controllerConfig:f.configFile}),dataDir:()=>f.root,
    isOwner:id=>String(id)===owner,on:(name,fn)=>{hooks[name]=fn;},context:fn=>contexts.push(fn),tool:fn=>tools.push(fn),
    defineTool:spec=>spec,every:(ms,fn)=>timers.push(fn),onDispose:fn=>dispose.push(fn),log:{warn(){}},
    ask:async opts=>{asked.push(opts); return '{"action":"start"}';},sendText:async(chatId,text)=>{sent.push({chatId,text});return {message_id:sent.length};}};
  const exports=setupAdapter(api);
  const where={sessionId:'live',level:'full',chat:{kind:'private',chatId:origin.chatId,userId:owner}};
  const cap=()=>contexts[0]({chat:where.chat}).match(/requestId=([a-f0-9-]{36})/)?.[1];
  return {api,exports,hooks,contexts,tools,timers,dispose,sent,asked,where,cap};
}
test('fake host：自然语言生成票据，模型工具单次执行；停用不处理消息',async t=>{
  const f=fixture(),h=host(f);t.after(()=>cleanActive(f.controller));
  await h.hooks.message(message('大肥鱼，帮我刷一下明日方舟日常'));
  assert.ok(h.cap());
  const tool=h.tools[0](h.where);
  const id=h.cap();
  assert.equal((await tool.execute({requestId:id})).code,'accepted');
  assert.equal((await tool.execute({requestId:id})).ok,false);
  await terminal(f.controller);
  await h.timers[0]();
  assert.equal(h.sent.length,2);
  h.dispose.forEach(fn=>fn());
  await h.hooks.message(message('帮我刷日常','2'));
  assert.equal(h.cap(),undefined); // Disposed context is disabled.
});
test('fake host：转发、引用、群聊、模拟、伪造解析正文均无法授权',async()=>{
  for(const mutate of [
    m=>{m.raw.simulated=true;},
    m=>{m.raw.message_type='group';m.kind='group';},
    m=>{m.raw.message=[{type:'forward',data:{id:'x'}}];},
    m=>{m.replyId='9';},
    m=>{m.raw.message[0].data.text='晚安';},
  ]) {
    const f=fixture(),h=host(f),m=message('帮我刷日常');
    mutate(m);await h.hooks.message(m);
    assert.equal(h.cap(),undefined);assert.equal(f.controller.active(),null);
    assert.equal(h.tools[0]({...h.where,sessionId:'sim'}),null);
  }
});
test('fake host：关闭 GUI 每次等待真实确认；拒绝/重放不执行',async t=>{
  const f=fixture('success',{guiBusy:true}),h=host(f);t.after(()=>cleanActive(f.controller));
  await h.hooks.message(message('帮我刷日常'));
  const result=await h.tools[0](h.where).execute({requestId:h.cap()});
  assert.equal(result.code,'gui_busy'); assert.equal(f.controller.active(),null);
  assert.match(h.sent[0].text,/未同意不会关闭/);
  await h.hooks.message(message('不同意','2'));
  assert.equal(f.controller.active(),null);
  await h.hooks.message(message('帮我刷日常','3'));
  await h.tools[0](h.where).execute({requestId:h.cap()});
  await h.hooks.message(message('同意，关闭原来的MAA并开始','4'));
  assert.equal(f.controller.active().status,'queued');
  await terminal(f.controller);
  const id=f.controller.active().id;
  await h.hooks.message(message('同意，关闭原来的MAA并开始','4'));
  assert.equal(f.controller.active().id,id);
});
test('fake host：确认前目标身份改变，拒绝执行并向主人反馈',async()=>{
  const f=fixture('success',{guiBusy:true}),h=host(f);
  await h.hooks.message(message('帮我刷日常'));
  await h.tools[0](h.where).execute({requestId:h.cap()});
  const file=path.join(f.root,'requests.json'),s=readJson(file);
  s.pending.target.pid=99;atomicJson(file,s);
  await h.hooks.message(message('允许','2'));
  assert.equal(f.controller.active(),null);
  assert.match(h.sent.at(-1).text,/身份已变化/);
});
test('fake host：旧模块 dispose 期间的异步意图结果不能生成票据',async()=>{
  const f=fixture(),h=host(f);
  let resolve;h.api.ask=()=>new Promise(r=>{resolve=r;});
  const work=h.hooks.message(message('请安排一下明日方舟的例行流程'));
  await until(()=>resolve);
  h.dispose.forEach(fn=>fn());
  resolve('{"action":"start"}');
  await work;
  assert.equal(h.cap(),undefined); assert.equal(f.controller.active(),null);
});

test('GUI 许可等待期间预设或控制配置变化，旧许可不能启动新计划',async()=>{
  const f=fixture('success',{guiBusy:true}),h=host(f);
  await h.hooks.message(message('帮我刷日常'));
  await h.tools[0](h.where).execute({requestId:h.cap()});
  const cfg=readJson(f.configFile);cfg.mock.stepSeconds=.2;atomicJson(f.configFile,cfg);
  await h.hooks.message(message('同意','2'));
  assert.equal(f.controller.active(),null);
  assert.match(h.sent.at(-1).text,/配置已变化/);
});


test('宿主总开关、dryRun 或主人权限撤销后，旧工具票据不能执行',async()=>{
  for(const cfg of [{enabled:false,ownerLevel:'full'}, {enabled:true,ownerLevel:'full',dryRun:true}, {enabled:true,ownerLevel:'chat'}]) {
    const f=fixture(),h=host(f);
    await h.hooks.message(message('帮我刷日常'));
    const cap=h.cap(),tool=h.tools[0](h.where);
    assert.ok(cap);
    h.api.config=()=>cfg;
    assert.equal((await tool.execute({requestId:cap})).ok,false);
    assert.equal(f.controller.active(),null);
  }
});

test('明确自然语言请求直接生成票据，不受分类模型格式或随机输出影响',async t=>{
  const f=fixture(),h=host(f);t.after(()=>cleanActive(f.controller));
  h.api.ask=async()=>{throw Error('明确请求不应依赖第二次模型分类');};
  await h.hooks.message(message('帮我把明日方舟日常清一下'));
  assert.ok(h.cap());assert.equal(h.asked.length,0);
  assert.equal((await h.tools[0](h.where).execute({requestId:h.cap()})).code,'accepted');
  await terminal(f.controller);
});

test('fake host：完成后明确强制退出绑定模拟器，保留任务结果并且不重复通知',async t=>{
  const f=fixture(),h=host(f);t.after(()=>cleanActive(f.controller));
  h.api.ask=async()=>{throw Error('明确请求不应依赖模型分类');};
  await h.hooks.message(message('帮我把明日方舟日常清一下'));
  await h.tools[0](h.where).execute({requestId:h.cap()});
  const before=await terminal(f.controller);
  await h.timers[0]();
  const noticeCount=h.sent.length;
  await h.hooks.message(message('强制退出模拟器','2'));
  const requestId=h.cap();
  assert.ok(requestId,'结束后明确关闭请求仍应生成票据');
  const result=await h.tools[0](h.where).execute({requestId});
  assert.equal(result.ok,true);
  assert.match(result.message,/绑定模拟器已关闭.*原任务结果保持不变/);
  const after=f.controller.active();
  for(const key of ['id','status','finishedAt','tasks','stats','warnings']) assert.deepEqual(after[key],before[key],key);
  assert.equal(after.cleanup.ok,true);
  assert.equal(after.emulatorClosed,true);
  assert.equal((await h.tools[0](h.where).execute({requestId})).ok,false);
  await h.timers[0]();
  assert.equal(h.sent.length,noticeCount,'清理不能再发开始、完成或取消通知');
  h.dispose.forEach(fn=>fn());
});
