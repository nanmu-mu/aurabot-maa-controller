import path from 'node:path';
import { importGui } from '../lib/preset.mjs';
import { readJson, TERMINAL } from '../lib/storage.mjs';
const [command,...args]=process.argv.slice(2);
function option(name) { const i=args.indexOf('--'+name); if(i<0 || !args[i+1]) throw new Error('缺少 --'+name); return path.resolve(args[i+1]); }
try {
  if(command==='convert') {
    const out=option('out'), data=args.includes('--data')?option('data'):null;
    if(data) {
      const a=readJson(path.join(data,'runtime','active.json'));
      const s=a?readJson(path.join(data,'runtime','runs',a.id,'state.json')):null;
      if(a && (!s || !TERMINAL.has(s.status) || !s.safeToRelease)) throw new Error('活动任务未结束，禁止同步预设');
    }
    const p=importGui(option('gui'),option('maa'),out);
    console.log('已生成专用预设：'+out+'\n任务：'+p.tasks.map(t=>t.type).join(' → ')+'\n未加载 Core、未连接 ADB、未启动模拟器。');
  } else throw new Error('用法：node scripts/cli.mjs convert --gui <gui.new.json> --maa <安装目录> --out <专用预设> [--data <模块数据目录>]');
} catch(e) { console.error(e.message); process.exitCode=1; }
