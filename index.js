import { setupAdapter } from './lib/adapter.mjs';
export default {
  id:'maa-controller',name:'Aurabot MAA Controller',version:'0.1.7',api:1,
  description:'主人私聊控制固定 MAA 日常；默认停用，真实执行需要单独启用。',
  defaults:{enabled:false,pythonPath:'python',controllerConfig:''},
  settings:[
    {key:'enabled',label:'启用请求处理',type:'switch',hint:'完成部署核验后启用；默认不接收执行请求。'},
    {key:'pythonPath',label:'Python 解释器完整路径',type:'text'},
    {key:'controllerConfig',label:'控制器配置完整路径',type:'text',hint:'留空使用本模块数据目录的 controller.json；切换后重载本模块。'}
  ],
  setup:setupAdapter
};
