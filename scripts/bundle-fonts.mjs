/**
 * npm 패키지의 woff2 를 www/fonts/ 로 복사한다.
 *
 * 앱은 오프라인에서 뜨는 게 존재 이유고, 계기판 서체가 이 앱의 정체성이다.
 * CDN 폰트는 갯바위에서 로드되지 않으므로 APK 안에 함께 담는다.
 * 웹(GitHub Pages)에는 www/fonts/ 가 없으므로 index.html 의 CDN 링크로 폴백된다.
 *
 * 파일명이 패키지 버전마다 바뀌므로 이름을 하드코딩하지 않고 탐색한다.
 * 못 찾아도 빌드를 세우지 않는다 — 시스템 폰트로 떨어질 뿐이다.
 */
import { readdirSync, statSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT  = join(ROOT, 'www', 'fonts');

/** 디렉터리 아래 모든 .woff2 경로 */
function walk(dir, acc = []) {
  if (!existsSync(dir)) return acc;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, acc);
    else if (name.toLowerCase().endsWith('.woff2')) acc.push(p);
  }
  return acc;
}

/** 후보 중 점수가 가장 높은 파일 하나 */
function pick(files, score) {
  let best = null, bs = -Infinity;
  for (const f of files) {
    const s = score(f.replace(/\\/g, '/').toLowerCase());
    if (s > bs) { bs = s; best = f; }
  }
  return bs > -Infinity ? best : null;
}

const TARGETS = [
  {
    pkg: 'pretendard',
    out: 'PretendardVariable.woff2',
    // 가변 폰트 · 서브셋 아닌 통짜 · 한글 포함본을 고른다
    score: p => (p.includes('variable') ? 100 : 0)
              + (p.includes('dynamic-subset') || /-\d+\.woff2$/.test(p) ? -80 : 0)
              + (p.includes('/std') || p.includes('jp') ? -50 : 0)
              + (p.includes('pretendardvariable.woff2') ? 60 : 0)
  },
  {
    pkg: '@fontsource-variable/jetbrains-mono',
    alt: '@fontsource/jetbrains-mono',
    out: 'JetBrainsMono.woff2',
    // 숫자·라벨 전용이라 latin 만 있으면 충분하다
    score: p => (p.includes('latin') && !p.includes('latin-ext') ? 100 : 0)
              + (p.includes('italic') ? -100 : 0)
              + (p.includes('wght') || p.includes('variable') ? 40 : 0)
              + (p.includes('-400-') ? 20 : 0)
  }
];

mkdirSync(OUT, { recursive: true });

let ok = 0;
for (const t of TARGETS) {
  const dirs = [t.pkg, t.alt].filter(Boolean).map(p => join(ROOT, 'node_modules', ...p.split('/')));
  const files = dirs.flatMap(d => walk(d));
  if (!files.length) {
    console.warn(`[fonts] ${t.pkg} 에서 woff2 를 찾지 못했습니다 — 시스템 폰트로 폴백됩니다.`);
    continue;
  }
  const src = pick(files, t.score);
  copyFileSync(src, join(OUT, t.out));
  const kb = Math.round(statSync(src).size / 1024);
  console.log(`[fonts] ${t.out}  ←  ${src.slice(ROOT.length + 1)}  (${kb}KB)`);
  ok++;
}

console.log(`[fonts] ${ok}/${TARGETS.length} 번들 완료 → www/fonts/`);
