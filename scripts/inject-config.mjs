/**
 * APK 안에 복사된 index.html 의 자리표시자를 실제 값으로 치환한다.
 *
 * `cap sync` 가 www/ 를 android/app/src/main/assets/public/ 로 복사한 **뒤**에
 * 실행한다. 원본 www/index.html 은 건드리지 않으므로 저장소가 더러워지지 않고,
 * 웹(Pages)에서는 자리표시자가 그대로 남아 상대경로 폴백이 동작한다.
 *
 *   PAGES_URL=https://user.github.io/repo REPO_SLUG=user/repo \
 *   APP_VERSION=1.0.0 node scripts/inject-config.mjs
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const TARGET = join(ROOT, 'android', 'app', 'src', 'main', 'assets', 'public', 'index.html');

if (!existsSync(TARGET)) {
  console.error('[inject] 대상이 없습니다. 먼저 `npx cap sync android` 를 실행하세요.\n  ' + TARGET);
  process.exit(1);
}

const VALUES = {
  __PAGES_URL__:   process.env.PAGES_URL   || '',
  __REPO_SLUG__:   process.env.REPO_SLUG   || '',
  __APP_VERSION__: process.env.APP_VERSION
                   || JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8')).version
};

let html = readFileSync(TARGET, 'utf8');
let missing = [];

for (const [ph, val] of Object.entries(VALUES)) {
  const n = html.split(ph).length - 1;
  if (n === 0) { console.log(`[inject] ${ph} 없음 (이미 치환됨)`); continue; }
  if (!val) { missing.push(ph); continue; }
  html = html.split(ph).join(val);
  console.log(`[inject] ${ph} → ${val}  (${n}곳)`);
}

writeFileSync(TARGET, html, 'utf8');

if (missing.length) {
  // 치명적이지 않다. PAGES_URL 이 없으면 앱은 정적 JSON 없이 뜨고
  // 조석은 근사, 법규는 씨드값으로 떨어진다 — 다만 조용히 그러면 곤란하다.
  console.warn(`\n[inject] 값이 비어 자리표시자로 남습니다: ${missing.join(', ')}`);
  console.warn('  → 앱은 동작하지만 조석·수온·법령 정적 JSON 을 받지 못합니다.');
}
