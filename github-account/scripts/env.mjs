/* 共享：从本 skill 目录的 .env 读配置（KEY=VALUE，支持 # 注释、export 前缀、引号、BOM），
 * 找不到再退回同名环境变量。git 仓库的 .gitignore 已忽略 .env。 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const SKILL_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export function envValue(keys, { fromProcessEnv = true } = {}) {
  const wanted = Array.isArray(keys) ? keys : [keys];
  const file = path.join(SKILL_ROOT, '.env');
  if (fs.existsSync(file)) {
    const text = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
    const found = {};
    for (const line of text.split(/\r?\n/)) {
      const m = /^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)$/.exec(line);
      if (!m) continue;
      let v = m[2].trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
      found[m[1]] = v.trim();
    }
    for (const k of wanted) if (found[k]) return found[k];
  }
  if (fromProcessEnv) {
    for (const k of wanted) {
      const v = (process.env[k] || '').trim();
      if (v) return v;
    }
  }
  return '';
}
