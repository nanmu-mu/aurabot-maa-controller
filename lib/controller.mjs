import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readJson, atomicJson, exclusiveJson, inside, requireId, TERMINAL } from './storage.mjs';
import { validatePreset, digest } from './preset.mjs';
const exec = promisify(execFile);
export class Controller {
  constructor({root, python, worker, configFile}) {
    this.now=()=>Date.now();
    this.root=path.resolve(root); this.python=python; this.worker=path.resolve(worker); this.configFile=configFile;
    fs.mkdirSync(this.root,{recursive:true});
  }
  config() {
    const c=readJson(this.configFile);
    if (!c || !['mock','real'].includes(c.mode)) throw new Error('控制器配置缺失或模式无效');
    if (c.mode==='real' && c.realEnabled!==true) throw new Error('真实执行尚未启用，需要阶段三确认');
    c.presetFile=path.resolve(path.dirname(this.configFile),c.presetFile);
    validatePreset(readJson(c.presetFile));
    return c;
  }
  jobPath(id) { return inside(this.root,'runs',requireId(id)); }
  state(id) { return readJson(path.join(this.jobPath(id),'state.json')); }
  forceInProgress(id) {
    const op=readJson(path.join(this.jobPath(id),'force.json'));
    if(op?.runId!==id || !Number.isInteger(op.pid) || op.pid<=0 || !Number.isFinite(op.at) || op.at>this.now()+5000 || op.at+30000<=this.now()) return false;
    try { process.kill(op.pid,0); return true; }
    catch(error) { return error.code==='EPERM'; }
  }
  active() {
    const a=readJson(path.join(this.root,'active.json'));
    if (!a) return null;
    const state=this.state(a.id);
    if (!state) return {...a,status:'unknown',reason:'任务账本缺失，禁止重复启动',safeToRelease:false};
    if (!TERMINAL.has(state.status)) {
      if(this.forceInProgress(a.id)) return {...state,forceInProgress:true};
      const proc=readJson(path.join(this.jobPath(a.id),'process.json'));
      const pid=proc?.pid || readJson(path.join(this.jobPath(a.id),'launcher.json'))?.pid;
      if (pid) {
        try { process.kill(pid,0); }
        catch(error) {
          if (error.code==='ESRCH') {
            const latest=this.state(a.id);
            if(latest && TERMINAL.has(latest.status)) return latest;
            Object.assign(state,latest || {});
            Object.assign(state,{status:'unknown',reason:'执行器意外退出，尚未确认最终结果',safeToRelease:false,finishedAt:Date.now()});
            atomicJson(path.join(this.jobPath(a.id),'state.json'),state);
          }
        }
      }
    }
    return state;
  }
  async helper(command, jobFile) {
    try {
      const {stdout}=await exec(this.python,['-B',this.worker,command,'--job',jobFile],{windowsHide:true,timeout:20000,maxBuffer:1024*1024,shell:false});
      return JSON.parse(stdout.trim());
    } catch(error) {
      let details; try { details=JSON.parse(error.stdout?.trim()); } catch {}
      throw new Error(details?.message || '执行器命令未完成，未证明操作成功');
    }
  }
  async start(origin,takeover=null,expectedPlan=null) {
    const gate=path.join(this.root,'start.lock');
    try { exclusiveJson(gate,{pid:process.pid}); }
    catch(error) {
      if(error.code!=='EEXIST') throw error;
      const old=readJson(gate);
      try { process.kill(old?.pid,0); } catch(e) { if(e.code==='ESRCH') fs.unlinkSync(gate); }
      return {ok:false,code:'busy',message:'另一个启动请求尚未结束，请稍后查询'};
    }
    try { return await this.startLocked(origin,takeover,expectedPlan); } finally { fs.unlinkSync(gate); }
  }
  async startLocked(origin, takeover=null,expectedPlan=null) {
    const active=this.active();
    if (active && (!TERMINAL.has(active.status) || !active.safeToRelease)) return {ok:false,code:'busy',state:active,message:'已有任务或状态未核清，不会重复启动'};
    const c=this.config();
    const id=randomUUID(), dir=this.jobPath(id);
    fs.mkdirSync(dir,{recursive:true});
    const job={schema:1,id,nonce:randomUUID(),origin,createdAt:Date.now(),config:c,preset:readJson(c.presetFile)};
    const planDigest=digest(JSON.stringify({config:c,preset:job.preset}));
    if(takeover && expectedPlan!==planDigest) throw new Error('预设或控制配置已变化，需要重新请求关闭许可');
    const jobFile=path.join(dir,'job.json');
    atomicJson(jobFile,job);
    // Inspect and takeover helpers cannot load Core or start the emulator.
    const probe=await this.helper('inspect',jobFile);
    if (probe.gui) {
      if (!takeover) return {ok:false,code:'gui_busy',target:probe.gui,planDigest,jobId:id,message:'现有 MAA GUI 阻塞；需要本次明确许可'};
      if (JSON.stringify(probe.gui)!==JSON.stringify(takeover)) throw new Error('MAA GUI 进程身份已变化，需要重新许可');
      const result=await this.helper('kill-gui',jobFileWithTarget(jobFile,job,takeover));
      if (!result.ok) throw new Error(result.message || '关闭 GUI 未得到确认');
    } else if (takeover) throw new Error('原获准关闭的 GUI 已变化；请重新发起');
    const pointer=path.join(this.root,'active.json');
    if (active) {
      const current=readJson(pointer);
      if (current?.id!==active.id) return {ok:false,code:'busy',message:'活动任务已变化'};
      fs.unlinkSync(pointer);
    }
    try { exclusiveJson(pointer,{id,createdAt:job.createdAt}); }
    catch(error) { if(error.code==='EEXIST') return {ok:false,code:'busy',message:'另一个请求已启动，不会重复启动'}; throw error; }
    atomicJson(path.join(dir,'state.json'),{id,status:'queued',mode:c.mode,origin,createdAt:job.createdAt,safeToRelease:false,tasks:{},stats:{},warnings:[]});
    let child;
    try {
      child=spawn(this.python,['-B',this.worker,'serve','--job',jobFile],{cwd:dir,windowsHide:true,detached:true,stdio:'ignore',shell:false});
      child.once('error',error=>atomicJson(path.join(dir,'state.json'),{id,status:'failed',mode:c.mode,origin,reason:'执行器未能启动：'+error.code,finishedAt:Date.now(),safeToRelease:true}));
      child.unref();
      // The worker owns state.json after launch; never overwrite its newer state.
      atomicJson(path.join(dir,'launcher.json'),{pid:child.pid || null,at:Date.now()});
    } catch(error) {
      atomicJson(path.join(dir,'state.json'),{id,status:'failed',mode:c.mode,origin,reason:'执行器未能创建',finishedAt:Date.now(),safeToRelease:true});
      throw error;
    }
    return {ok:true,code:'accepted',runId:id,message:(c.mode==='mock'?'【模拟】':'')+'已受理，尚未证明开始，更不代表完成'};
  }
  async control(kind,origin) {
    const s=this.active();
    if (!s) return {ok:false,message:'没有插件任务'};
    if (s.origin?.userId!==origin.userId || s.origin?.chatId!==origin.chatId) throw new Error('任务不属于当前授权私聊');
    if (kind==='status' || (kind==='stop' && TERMINAL.has(s.status) && s.safeToRelease)) return {ok:true,state:s,message:formatState(s)};
    const dir=this.jobPath(s.id);
    if (kind==='stop') {
      if(s.status==='unknown') return {ok:false,message:'原结果未知，无法确认温和停止；请先核对或明确要求强制清理绑定实例'};
      atomicJson(path.join(dir,'control.json'),{id:randomUUID(),kind:'stop',at:Date.now()});
      return {ok:true,message:'已请求温和停止，正在等待实际停止；不会自动强杀'};
    }
    if (kind==='force') return this.helper('force',path.join(dir,'job.json'));
    throw new Error('不支持的操作');
  }
  async notify(send,isOwner) {
    if (this.notifying) return;
    this.notifying=true;
    try {
      const runs=path.join(this.root,'runs');
      if(!fs.existsSync(runs)) return;
      for(const id of fs.readdirSync(runs).filter(x=>/^[a-f0-9-]{36}$/.test(x))) {
        const dir=this.jobPath(id), s=this.state(id);
        if(!s?.origin || !isOwner(s.origin.userId) || this.forceInProgress(id)) continue;
        const notices=readJson(path.join(dir,'notices.json'),{});
        for(const phase of ['start','attention','finish']) {
          const kind=phase==='attention'?'attention-'+(s.attentionKey || 'general'):phase;
          if(notices[kind]==='sent' || (notices[kind+'RetryAt'] || 0)>this.now()) continue;
          if(kind==='start' && !s.startedAt) continue;
          if(phase==='attention' && (!s.attention || TERMINAL.has(s.status))) continue;
          if(kind==='finish' && !TERMINAL.has(s.status)) continue;
          if(kind==='finish' && s.startedAt && notices.start!=='sent') continue;
          const lock=path.join(dir,'notice-'+kind+'.lock');
          try { exclusiveJson(lock,{pid:process.pid}); }
          catch(error) {
            if(error.code!=='EEXIST') throw error;
            const old=readJson(lock);
            try { process.kill(old?.pid,0); } catch(e) { if(e.code==='ESRCH') fs.unlinkSync(lock); }
            continue;
          }
          try {
            const fresh=readJson(path.join(dir,'notices.json'),{});
            if(fresh[kind]==='sent') continue;
            const prefix=s.mode==='mock'?'【模拟】':'';
            const text=kind==='start'?prefix+'MAA 日常已实际开始。':phase==='attention'?prefix+'MAA 需要处理：'+s.attention:formatState(s);
            let ack=null;
            try { ack=await send(s.origin.chatId,text); } catch {}
            if(ack) { fresh[kind]='sent'; notices[kind]='sent'; }
            else fresh[kind+'RetryAt']=this.now()+30000;
            atomicJson(path.join(dir,'notices.json'),fresh);
          } finally { fs.unlinkSync(lock); }
        }
      }
    } finally { this.notifying=false; }
  }
}
function jobFileWithTarget(file,job,target) {
  const targetFile=path.join(path.dirname(file),'takeover.json');
  atomicJson(targetFile,{...job,target});
  return targetFile;
}
const titles={success:'预设执行完成',partial:'预设部分完成',failed:'执行失败',cancelled:'本次任务已取消',unknown:'最终状态未知',queued:'已受理，等待启动',connecting:'正在连接模拟器',running:'正在执行',stopping:'正在等待温和停止'};
const taskNames={StartUp:'唤醒',Recruit:'公招',Infrast:'基建',Fight:'作战',Mall:'信用',Award:'领奖'};
export function formatState(s) {
  const lines=[(s.mode==='mock'?'【模拟】':'')+'MAA：'+(s.forceInProgress?'正在强制终止，等待关闭确认':titles[s.status]||'状态未知')];
  if(s.currentTask) lines.push('阶段：'+(taskNames[s.currentTask]||s.currentTask));
  if(s.reason) lines.push(s.reason);
  if(s.tasks) lines.push(Object.entries(s.tasks).map(([k,v])=>(taskNames[k]||k)+'：'+({completed:'完成',error:'失败',stopped:'停止',pending:'未确认',running:'进行中'}[v]||v)).join('；'));
  const st=s.stats || {};
  if(st.battles!==undefined) lines.push('已识别完成场次：'+st.battles+(st.incomplete?'（统计不完整）':''));
  const drops=Object.values(st.drops || {}).slice(0,12);
  if(drops.length) lines.push('已识别掉落：'+drops.map(x=>String(x.name).slice(0,40)+' × '+x.quantity).join('，'));
  if(st.recruitRefreshes) lines.push('公招已识别刷新：'+st.recruitRefreshes+' 次；标签预测不代表实际获得干员');
  if(st.incomplete) lines.push('仅列已识别部分，不是完整资产账单。');
  const checks=(s.subtaskDiagnostics || []).filter(x=>x.kind==='condition');
  if(checks.length) lines.push('条件检测未命中（不等同任务失败）：'+checks.slice(0,8).map(x=>x.label+' × '+x.count).join('，'));
  const skipped=(s.subtaskDiagnostics || []).filter(x=>x.kind==='skipped');
  if(skipped.length) lines.push('正常跳过：'+skipped.map(x=>x.label).join('，'));
  if(s.cleanup) lines.push(s.cleanup.ok?'绑定模拟器已关闭；原任务结果保持不变。':'绑定模拟器关闭未确认：'+s.cleanup.reason+'；原任务结果保持不变。');
  else if(s.emulatorClosed===false) lines.push('执行器已停止，但绑定模拟器未能确认关闭。');
  for(const w of (s.warnings || []).slice(-3)) lines.push(w);
  return lines.filter(Boolean).join('\n');
}
