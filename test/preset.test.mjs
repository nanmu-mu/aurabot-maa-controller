import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { validatePreset, convertGui } from '../lib/preset.mjs';
import { readJson } from '../lib/storage.mjs';
import { project } from './helpers.mjs';
const preset=readJson(path.join(project,'presets','daily.json'));
function gui() {
  const q=[
    {TaskType:'StartUp',IsEnable:true,AccountSwitchEnabled:false,AccountName:''},
    {TaskType:'Recruit',IsEnable:true,RefreshLevel3:true,Level3Choose:true,Level4Choose:true,Level5Choose:false,Level6Choose:false,MaxTimes:4,Level3Time:540,Level4Time:540,ExtraTagMode:0,PreferTagEnabled:true,Level3PreferTags:[],PreserveTagEnabled:true,PreserveTagList:['支援机械'],ForceRefresh:true,Level3RecruitmentPermitReserveEnabled:false},
    {TaskType:'Infrast',IsEnable:true,Mode:'Rotation',Filename:'',UsesOfDrones:'Money',DormThreshold:30,OriginiumShardAutoReplenishment:true,DormFilterNotStationed:true,DormTrustEnabled:false,ReceptionMessageBoard:true,ReceptionClueExchange:true,SendClue:true,ContinueTraining:false,RoomList:[{Room:'Mfg'},{Room:'Trade'},{Room:'Recycle',IsEnabled:false}]},
    {TaskType:'Fight',IsEnable:true,UseMedicine:false,MedicineCount:20,UseStone:false,UseExpiringMedicine:false,StagePlan:['1-7'],EnableTimesLimit:true,TimesLimit:999,Series:6},
    {TaskType:'Mall',IsEnable:true,Shopping:true,VisitFriends:true,CreditFight:false,VisitFriendsOnceADay:false,FirstList:'招聘许可',BlackList:'碳;家具;加急许可',ShoppingIgnoreBlackListWhenFull:false,OnlyBuyDiscount:false,ReserveMaxCredit:false},
    {TaskType:'Award',IsEnable:true,Award:true}
  ];
  return {Current:'Default',Configurations:{Default:{TaskQueue:q,Gui:{
    ConnectSettings:{Config:'MuMuEmulator12',TouchMode:'MiniTouch',EnableAdbLite:false,Extras:{}},
    RuntimeSettings:{ClientType:'Official',StartGame:true},ThirdParty:{PenguinId:'NEVER_COPY_THIS_ID',Token:'NEVER_COPY_THIS_SECRET',ReportToPenguin:true}}}}};
}
test('受控转换保留有效策略，未启用 MedicineCount=20 绝不变成吃药',()=>{
  const p=convertGui(gui(),preset.sourceHashes);
  assert.equal(p.tasks[3].params.medicine,0);
  assert.equal(p.tasks[2].params.mode,20000);
  assert.equal(p.tasks[2].params.replenish,true);
  assert.deepEqual(p.tasks[2].params.facility,['Mfg','Trade']);
  assert.equal(p.tasks[1].params.expedite,false);
  assert.deepEqual(p.tasks[1].params.recruitment_time,{'3':540,'4':540,'5':540,'6':540});
  assert.ok(p.tasks[4].params.blacklist.includes('嘉维尔'));
  assert.equal(p.tasks[5].params.recruit,false);
  assert.equal(JSON.stringify(p).includes('NEVER_COPY'),false);
  assert.equal(p.tasks[3].params.report_to_penguin,false);
});
test('敏感入口、非白名单任务、账号切换和连接变化均拒绝',()=>{
  for(const modify of [
    p=>p.maaVersion='6.21.1',
    p=>p.maaVersion='6.21.4',
    p=>p.tasks[3].params.stone=1,
    p=>p.tasks[3].params.medicine=20,
    p=>p.tasks[5].params.recruit=true,
    p=>p.tasks[1].params.expedite=true,
    p=>p.tasks[1].params.confirm.push(5),
    p=>p.tasks[3].params.report_to_penguin=true,
    p=>p.tasks[0].params.account_name='other',
    p=>p.tasks[0].params.command='anything',
    p=>p.tasks.push({type:'Custom',params:{}}),
    p=>delete p.tasks[5].params.mail,
    p=>p.connection.touchType='unknown'
  ]) {const p=structuredClone(preset);modify(p);assert.throws(()=>validatePreset(p));}
  const g=gui();g.Configurations.Default.Gui.ConnectSettings.Extras.MuMuEmulator12={IsEnabled:true};
  assert.throws(()=>convertGui(g,{}),/增强截图/);
});
test('已转换的实际预设只有已同意资源路径，无第三方身份、脚本或凭证字段',()=>{
  validatePreset(preset);
  assert.equal(preset.tasks[2].params.replenish,true);
  assert.equal(preset.tasks[3].params.stone,0);
  assert.equal(preset.tasks[5].params.recruit,false);
  assert.equal(/penguin_id|yituliu_id|token|password|script/i.test(JSON.stringify(preset)),false);
});
