import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export function readJson(file, fallback = null) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')); }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
}
export function atomicJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = file + '.' + randomUUID() + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(tmp, file);
}
export function exclusiveJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const fd = fs.openSync(file, 'wx', 0o600);
  try { fs.writeFileSync(fd, JSON.stringify(value)); } finally { fs.closeSync(fd); }
}
export function inside(root, ...parts) {
  const base = path.resolve(root);
  const file = path.resolve(base, ...parts);
  if (file !== base && !file.startsWith(base + path.sep)) throw new Error('路径越界');
  return file;
}
export function requireId(id) {
  if (!/^[a-f0-9-]{36}$/.test(String(id))) throw new Error('无效请求编号');
  return id;
}
export const TERMINAL = new Set(['success', 'partial', 'failed', 'cancelled', 'unknown']);
