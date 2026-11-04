import { randomUUID } from 'node:crypto';
import { readJson, atomicJson } from './storage.mjs';

export function trustedMessage(msg,isOwner,now=Date.now()) {
  const e=msg?.raw;
  if(!e || e.simulated || e.post_type!=='message' || e.message_type!=='private' || msg.kind!=='private') return null;
  const uid=String(e.user_id || ''), mid=String(e.message_id || '');
  if(!uid || !mid || !isOwner(uid) || String(msg.userId)!==uid || String(msg.messageId)!==mid || msg.chatId!=='private:'+uid) return null;
  if(!Number.isFinite(e.time) || Math.abs(now-e.time*1000)>120000) return null;
  if(msg.replyId || msg.forwards?.length || (e.sender?.user_id && String(e.sender.user_id)!==uid)) return null;
  let text='';
  if(Array.isArray(e.message)) {
    if(e.message.some(s=>s.type!=='text' || typeof s.data?.text!=='string')) return null;
    text=e.message.map(s=>s.data.text).join('').trim();
  } else if(typeof e.message==='string' && !e.message.includes('[CQ:')) text=e.message.trim();
  if(!text || text.length>500 || /["“”「」『』\x60]|https?:\/\/|转发|引用|聊天记录|他说|她说|提示词|忽略.{0,8}规则|powershell|\bcmd\b/i.test(text)) return null;
  return {text,userId:uid,chatId:msg.chatId,messageId:mid,receivedAt:e.time*1000};
}
export function plausible(action,text,active=false) {
  if(action==='stop' && active && /^(?:大肥鱼[，, ]*)?(?:别刷了|不刷了|不要继续刷了)[。！! ]*$/.test(text)) return true;
  if(/不要|别|不想|不用|不能|取消授权|明天|定时|假如|如果|例如|比如|如何|怎么|能做什么/.test(text)) return false;
  const topic=/MAA|明日方舟|日常/i.test(text);
  if(action==='start' && /[?？]|假设|讨论|能否|是否/.test(text)) return false;
  if(action==='start') return topic && /帮我|麻烦|请|开始|启动|执行|刷|清一下|清理|清掉/.test(text) && !/停止|终止|状态|进度|结束了吗/.test(text);
  if(action==='force') return (topic || active) && /强制.{0,5}(停|终止|结束|关)|强杀/.test(text) && !/全部|所有|全局/.test(text);
  if(action==='stop') return (topic || active) && /停止|停下|停一下|结束本次|取消.{0,5}(任务|日常)/.test(text) && !/强制|强杀/.test(text);
  if(action==='status') return (topic || active) && /状态|进度|怎么样|结束了吗|完成了吗|刷完了吗|正在.*吗/.test(text);
  return false;
}
export function consent(text) {
  if(/不|别|等一下|稍后|以后|明天|等我|定时|取消|拒绝/.test(text)) return 'no';
  if(/^(同意|允许|可以|确认|好[的啊]?|行)([，,。！! ]|$)/.test(text)) return 'yes';
  return null;
}
export class Tickets {
  constructor(file) { this.file=file; }
  load() { return readJson(this.file,{seen:[],caps:[],pending:null}); }
  save(s) { atomicJson(this.file,s); }
  seen(messageId) {
    const s=this.load();
    if(s.seen.includes(messageId)) return true;
    s.seen=[...s.seen,messageId].slice(-512);
    s.caps=s.caps.filter(x=>x.expires>Date.now() && !x.used);
    this.save(s); return false;
  }
  issue(origin,action) {
    const s=this.load(), cap={...origin,text:undefined,id:randomUUID(),action,expires:Math.min(Date.now()+120000,(origin.receivedAt || Date.now())+120000)};
    s.caps.push(cap); this.save(s); return cap;
  }
  consume(id,where,isOwner) {
    const s=this.load(), c=s.caps.find(x=>x.id===id);
    if(where.sessionId==='sim' || where.level!=='full' || !c || c.used || c.expires<Date.now() || where.chat?.kind!=='private' || !isOwner(c.userId)
      || where.chat.chatId!==c.chatId || String(where.chat.userId)!==c.userId) throw new Error('缺少当前真实主人私聊的一次性请求票据');
    c.used=true; this.save(s); return c;
  }
  revoke(origin) {
    const s=this.load();
    for(const c of s.caps) if(c.chatId===origin.chatId && c.userId===origin.userId && !c.used) c.used=true;
    if(s.pending?.origin.chatId===origin.chatId) s.pending=null;
    this.save(s);
  }
  context(chatId) {
    return this.load().caps.filter(c=>c.chatId===chatId && !c.used && c.expires>Date.now())
      .map(c=>'MAA 待执行请求：requestId='+c.id+'；动作='+c.action+'。仅可调用 maa_control 消费该票据；已受理不代表开始或完成。').join('\n');
  }
  pending(origin,target,planDigest) {
    const s=this.load();
    if(s.pending && s.pending.expires>Date.now()) throw new Error('已有 GUI 关闭请求等待确认，不会替换目标');
    s.pending={id:randomUUID(),origin:{userId:origin.userId,chatId:origin.chatId,messageId:origin.messageId},target,planDigest,expires:Date.now()+300000};
    this.save(s); return s.pending;
  }
  takePending(origin) {
    const s=this.load(), p=s.pending;
    if(!p || p.expires<Date.now() || p.origin.userId!==origin.userId || p.origin.chatId!==origin.chatId) return null;
    s.pending=null; this.save(s); return p;
  }
}

export function parseIntentResponse(response) {
  if(typeof response!=='string') return {action:'none',format:'invalid'};
  let text=response.trim(),format='json';
  const fenced=text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if(fenced) { text=fenced[1]; format='fenced-json'; }
  try {
    const value=JSON.parse(text);
    if(Object.keys(value).length!==1 || !['start','status','stop','force','none'].includes(value.action)) return {action:'none',format:'invalid'};
    return {action:value.action,format};
  } catch { return {action:'none',format:'invalid'}; }
}


export function directIntent(text,active=false) {
  // Whole-sentence imperatives only. Negations/quotes/plans still use the existing gates.
  const s=text.replace(/[\s，,。！!]/g,'').replace(/^大肥鱼/,'');
  const prefix='(?:请(?:你)?帮我|麻烦(?:你)?帮我|请(?:你)?|麻烦(?:你)?|帮我|替我)?';
  const topic='(?:(?:明日方舟|MAA)(?:的)?(?:日常)?|日常)';
  const verb='(?:刷(?:一下)?|清(?:一下|理|掉)?|跑(?:一下)?|做(?:一下)?|执行(?:一下)?|启动|开始)';
  if(new RegExp('^'+prefix+'(?:把)?(?:'+verb+topic+'|'+topic+verb+')(?:吧|啦|哦)?$','i').test(s) && plausible('start',text,active)) return 'start';
  if(active && /^(?:请|帮我)?(?:强制终止|强制停止|强杀)(?:本次)?(?:MAA|明日方舟|日常|任务|模拟器)?$/i.test(s) && plausible('force',text,true)) return 'force';
  if(active && /^(?:请|帮我)?(?:温和停止|停止|停下|停一下|别刷了|不刷了)(?:本次)?(?:MAA|明日方舟|日常|任务)?$/i.test(s) && plausible('stop',text,true)) return 'stop';
  if(/^(?:MAA|明日方舟|日常|任务)?(?:状态|进度|刷完了吗|完成了吗|结束了吗)$/i.test(s) && plausible('status',text,active)) return 'status';
  return null;
}
