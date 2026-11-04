import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { readJson, atomicJson } from './storage.mjs';

export const ORDER = ['StartUp','Recruit','Infrast','Fight','Mall','Award'];
const allow = {
  StartUp: ['client_type','start_game_enabled','account_name'],
  Recruit: ['refresh','select','confirm','times','set_time','expedite','recruitment_time','report_to_penguin','report_to_yituliu','extra_tags_mode','first_tags','preserve_tags','force_refresh','level3_recruitment_permit_reserve'],
  Infrast: ['mode','facility','drones','threshold','replenish','dorm_notstationed_enabled','dorm_trust_enabled','reception_message_board','reception_clue_exchange','reception_send_clue','continue_training','fiammetta_recovery_enabled','use_pinus_sylvestris','use_perception_information','use_worldly_plight','use_abyssal_hunter'],
  Fight: ['stage','times','series','medicine','medicine_expire_days','stone','DrGrandet','report_to_penguin','report_to_yituliu','client_type'],
  Mall: ['shopping','visit_friends','credit_fight','buy_first','blacklist','force_shopping_if_credit_full','only_buy_discount','reserve_max_credit','formation_index'],
  Award: ['award','mail','recruit','orundum','mining','specialaccess','signinevent']
};
export const digest = bytes => createHash('sha256').update(bytes).digest('hex');
export function treeDigest(root, dllsOnly=false) {
  const files=[];
  function walk(dir) {
    for(const e of fs.readdirSync(dir,{withFileTypes:true})) {
      if(e.isSymbolicLink()) throw new Error('版本资源不得包含符号链接');
      const full=path.join(dir,e.name);
      if(e.isDirectory() && !dllsOnly && (dir!==root || e.name==='tasks')) walk(full);
      else if(e.isFile() && (dllsOnly ? e.name.toLowerCase().endsWith('.dll') : e.name.toLowerCase().endsWith('.json'))) files.push(path.relative(root,full).split(path.sep).join('/'));
    }
  }
  walk(root);
  files.sort((a,b)=>Buffer.compare(Buffer.from(a),Buffer.from(b)));
  const hash=createHash('sha256');
  for(const n of files) hash.update(n+'\0'+digest(fs.readFileSync(path.join(root,n)))+'\n');
  return hash.digest('hex');
}
export function fingerprints(maaDir) {
  return {'core-dlls':treeDigest(maaDir,true),'resource-definitions':treeDigest(path.join(maaDir,'resource'))};
}
export function validatePreset(preset) {
  if (preset?.schema !== 1 || preset.maaVersion !== '6.21.3') throw new Error('仅支持已核查的 MAA 6.21.3 预设');
  if (preset.connection?.profile!=='MuMuEmulator12' || preset.connection.touchType!=='minitouch' || preset.connection.adbLiteEnabled!==false || Object.keys(preset.connection).length!==3) throw new Error('连接参数未经核验');
  if (JSON.stringify(preset.tasks?.map(t => t.type)) !== JSON.stringify(ORDER)) throw new Error('只允许六项固定任务及其顺序');
  for (const {type,params:p} of preset.tasks) {
    if (!p || JSON.stringify(Object.keys(p).sort())!==JSON.stringify([...allow[type]].sort())) throw new Error('不支持的任务参数');
    if (('report_to_penguin' in p && p.report_to_penguin!==false) || ('report_to_yituliu' in p && p.report_to_yituliu!==false)) throw new Error('禁止外部统计上报');
    if (type === 'StartUp' && (p.client_type !== 'Official' || p.account_name !== '' || p.start_game_enabled !== true)) throw new Error('禁止账号切换');
    if (type === 'Recruit' && (p.expedite !== false || p.confirm?.some(x=>![3,4].includes(x)) || p.select?.some(x=>x!==4))) throw new Error('公招安全策略不符');
    if (type === 'Infrast' && (p.mode !== 20000 || !Array.isArray(p.facility) || p.facility.some(x=>!['Mfg','Trade','Control','Power','Reception','Office','Dorm','Processing','Training'].includes(x)))) throw new Error('只支持当前基建轮换模式');
    if (type === 'Fight' && (p.stage !== '1-7' || p.stone !== 0 || p.medicine !== 0 || p.medicine_expire_days !== 0 || p.DrGrandet !== false)) throw new Error('禁止改变关卡或消耗药剂/源石');
    if (type === 'Mall' && p.credit_fight !== false) throw new Error('不启用信用战');
    if (type === 'Award' && (p.award !== true || Object.entries(p).some(([k,v])=>k!=='award' && v!==false))) throw new Error('只领取每日/每周任务奖励');
  }
  return preset;
}
function expect(condition, text) { if (!condition) throw new Error(text); }
function list(s) { return String(s || '').split(/[;；,，]/).map(x=>x.trim()).filter(Boolean); }
export function convertGui(gui, sourceHashes) {
  expect(gui.Current === 'Default', '首版只转换 Default；其他配置需重新核查');
  const q = gui.Configurations?.Default?.TaskQueue?.filter(t=>t.IsEnable);
  expect(JSON.stringify(q?.map(t=>t.TaskType)) === JSON.stringify(ORDER), '启用任务与已确认六项预设不一致');
  const [s,r,i,f,m,a]=q;
  const connection=gui.Configurations.Default.Gui?.ConnectSettings;
  const runtime=gui.Configurations.Default.Gui?.RuntimeSettings;
  expect(connection?.Config==='MuMuEmulator12' && connection.TouchMode==='MiniTouch' && connection.EnableAdbLite===false && !connection.Extras?.MuMuEmulator12?.IsEnabled && !connection.Extras?.LDPlayer?.IsEnabled, '连接模式或增强截图超出当前已核查配置');
  expect(runtime?.ClientType==='Official' && runtime.StartGame===true, '仅支持现有官服启动配置');
  expect(!s.AccountSwitchEnabled && !s.AccountName, '不迁移账号信息');
  expect(!f.UseStone && !f.UseMedicine && !f.UseExpiringMedicine, '现配置启用了药剂/源石，请先明确关闭');
  expect(!f.EnableTargetDrop && !f.UseWeeklySchedule && !f.UseOptionalStage && f.StagePlan?.length===1 && f.StagePlan[0]==='1-7', '不支持动态关卡、目标掉落或周计划');
  expect(i.Mode==='Rotation' && !i.Filename && !i.UseWeeklySchedule && !i.FiammettaRecoveryEnabled && !i.UsePinusSylvestris && !i.UsePerceptionInformation && !i.UseWorldlyPlight && !i.UseAbyssalHunter, '基建模式/特殊策略超出已核查范围');
  expect(!r.Level5Choose && !r.Level6Choose, '不允许自动确认五星/六星');
  expect(!m.CreditFight && !m.VisitFriendsOnceADay, '当前转换不支持信用战或跨运行好友访问记账');
  expect(a.Award && !a.Mail && !a.FreeGacha && !a.Orundum && !a.Mining && !a.SpecialAccess && !a.SignInEvent, '奖励配置超出当前范围');
  const tasks = [
    {type:'StartUp', params:{client_type:'Official',start_game_enabled:true,account_name:''}},
    {type:'Recruit', params:{
      refresh:r.RefreshLevel3,select:r.Level4Choose?[4]:[],confirm:[...(r.Level3Choose?[3]:[]),...(r.Level4Choose?[4]:[])],
      times:r.MaxTimes,set_time:true,expedite:false,recruitment_time:{'3':r.Level3Time,'4':r.Level4Time,'5':540,'6':540},
      report_to_penguin:false,report_to_yituliu:false,extra_tags_mode:r.ExtraTagMode,
      first_tags:r.PreferTagEnabled?r.Level3PreferTags:[],preserve_tags:r.PreserveTagEnabled?r.PreserveTagList:[],
      force_refresh:r.ForceRefresh,level3_recruitment_permit_reserve:r.Level3RecruitmentPermitReserveEnabled?r.Level3RecruitmentPermitReserve:0}},
    {type:'Infrast', params:{mode:20000,facility:i.RoomList.filter(x=>x.IsEnabled!==false).map(x=>x.Room),drones:i.UsesOfDrones,
      threshold:i.DormThreshold/100,replenish:i.OriginiumShardAutoReplenishment,dorm_notstationed_enabled:i.DormFilterNotStationed,
      dorm_trust_enabled:i.DormTrustEnabled,reception_message_board:i.ReceptionMessageBoard,
      reception_clue_exchange:i.ReceptionClueExchange,reception_send_clue:i.SendClue,continue_training:i.ContinueTraining,
      fiammetta_recovery_enabled:false,use_pinus_sylvestris:false,use_perception_information:false,use_worldly_plight:false,use_abyssal_hunter:false}},
    {type:'Fight',params:{stage:'1-7',times:f.EnableTimesLimit?f.TimesLimit:999,series:f.Series,medicine:0,medicine_expire_days:0,stone:0,DrGrandet:false,
      report_to_penguin:false,report_to_yituliu:false,client_type:'Official'}},
    {type:'Mall',params:{shopping:m.Shopping,visit_friends:m.VisitFriends,credit_fight:false,formation_index:0,buy_first:list(m.FirstList),
      blacklist:[...new Set([...list(m.BlackList),'讯使','嘉维尔','坚雷'])],force_shopping_if_credit_full:m.ShoppingIgnoreBlackListWhenFull,
      only_buy_discount:m.OnlyBuyDiscount,reserve_max_credit:m.ReserveMaxCredit}},
    {type:'Award',params:{award:true,mail:false,recruit:false,orundum:false,mining:false,specialaccess:false,signinevent:false}}
  ];
  return validatePreset({schema:1,maaVersion:'6.21.3',sourceProfile:'Default',connection:{profile:'MuMuEmulator12',touchType:'minitouch',adbLiteEnabled:false},sourceHashes,tasks});
}
export function importGui(guiFile, maaDir, output) {
  const preset=convertGui(readJson(guiFile),fingerprints(maaDir));
  atomicJson(output,preset);
  return preset;
}
