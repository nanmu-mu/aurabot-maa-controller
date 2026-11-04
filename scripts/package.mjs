import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const destination=path.join(root,'dist','maa-controller');
if(fs.existsSync(destination)) throw new Error('构建目录已存在；请归档后使用新的干净构建目录，避免混入旧文件');
fs.mkdirSync(destination,{recursive:true});
const files=['index.js','package.json','controller.example.json','README.md','LICENSE','NOTICE','THIRD-PARTY-NOTICES.md','CHANGELOG.md','CONTRIBUTING.md','RELEASE_NOTES.md','presets/daily.json','scripts/cli.mjs','scripts/deploy.mjs','docs/SPEC.md','docs/INSTALL.md','docs/VALIDATION.md','docs/INTEGRATION.md'];
for(const folder of ['lib','worker']) {
  for(const name of fs.readdirSync(path.join(root,folder))) if(/\.(mjs|py)$/.test(name)) files.push(folder+'/'+name);
}
const hashes={};
for(const name of files) {
  const bytes=fs.readFileSync(path.join(root,name));
  const target=path.join(destination,name);
  fs.mkdirSync(path.dirname(target),{recursive:true});
  fs.writeFileSync(target,bytes);
  hashes[name]=createHash('sha256').update(bytes).digest('hex');
}
fs.writeFileSync(path.join(destination,'manifest.json'),JSON.stringify({version:JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version,realEnabled:false,files:hashes},null,2));
console.log(destination);
