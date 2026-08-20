/**
 * `npx cap add android` 가 만든 안드로이드 프로젝트에 이 앱의 요구사항을 입힌다.
 *
 * android/ 는 커밋하지 않는다(.gitignore). CI 가 매 빌드마다 새로 만들고
 * 이 스크립트가 같은 패치를 다시 입힌다 — 손으로 고친 것이 조용히 사라지는
 * 이중 관리를 피하기 위해서다. 안드로이드 쪽을 바꿀 일이 생기면 여기를 고친다.
 *
 * 모든 패치는 멱등이다. 이미 적용돼 있으면 건너뛴다.
 *
 *   node scripts/patch-android.mjs
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const A = join(ROOT, 'android');

if (!existsSync(A)) {
  console.error('[patch] android/ 가 없습니다. 먼저 `npx cap add android` 를 실행하세요.');
  process.exit(1);
}

const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
const VERSION = pkg.version;
const VERSION_CODE = process.env.VERSION_CODE || '1';

let changed = 0, skipped = 0;

/** 파일을 읽어 변환 함수를 적용한다. 반환값이 null 이면 변경 없음. */
function edit(rel, label, fn) {
  const p = join(A, rel);
  if (!existsSync(p)) {
    console.error(`[patch] ${rel} 이(가) 없습니다 — Capacitor 버전이 바뀌었을 수 있습니다.`);
    process.exit(1);
  }
  const before = readFileSync(p, 'utf8');
  const after = fn(before);
  if (after == null || after === before) {
    console.log(`[=] ${label}`);
    skipped++;
    return;
  }
  writeFileSync(p, after, 'utf8');
  console.log(`[+] ${label}`);
  changed++;
}

/** 앵커가 없으면 Capacitor 템플릿이 바뀐 것이므로 조용히 넘어가지 않고 세운다. */
function need(src, anchor, label) {
  if (!src.includes(anchor)) {
    console.error(`[patch] ${label}: 앵커를 찾지 못했습니다 →\n    ${anchor}`);
    process.exit(1);
  }
}

// ── 1. minSdk 26 (Android 8.0) ──────────────────────────────────
edit('variables.gradle', 'minSdk 26', src => {
  if (/minSdkVersion\s*=\s*26\b/.test(src)) return null;
  need(src, 'minSdkVersion', 'variables.gradle');
  return src.replace(/minSdkVersion\s*=\s*\d+/, 'minSdkVersion = 26');
});

// ── 2. 버전 · 서명 설정 ─────────────────────────────────────────
edit('app/build.gradle', `버전(${VERSION} / code ${VERSION_CODE}) · 서명 설정`, src => {
  let s = src;

  s = s.replace(/versionCode\s+\d+/, `versionCode ${VERSION_CODE}`);
  s = s.replace(/versionName\s+"[^"]*"/, `versionName "${VERSION}"`);

  if (!s.includes('signingConfigs {')) {
    need(s, '    buildTypes {', 'app/build.gradle buildTypes');
    s = s.replace('    buildTypes {', `    // 키스토어와 비밀번호는 저장소에 없다. CI 시크릿 또는 로컬 환경변수로 넣는다.
    // 키스토어를 잃어버리면 기존 설치본에 업데이트를 못 올린다 — 반드시 백업할 것.
    signingConfigs {
        release {
            storeFile file(System.getenv("KEYSTORE_PATH") ?: "release.keystore")
            storePassword System.getenv("KEYSTORE_PASSWORD")
            keyAlias System.getenv("KEY_ALIAS")
            keyPassword System.getenv("KEY_PASSWORD")
        }
    }

    buildTypes {`);
  }

  if (!s.includes('signingConfig signingConfigs.release')) {
    need(s, '        release {\n            minifyEnabled false', 'app/build.gradle release 블록');
    s = s.replace('        release {\n            minifyEnabled false',
      '        release {\n            signingConfig signingConfigs.release\n            minifyEnabled false');
  }

  return s;
});

// ── 3. 매니페스트 — 세로 고정 · 평문 트래픽 차단 ────────────────
//
// 위치 권한은 선언하지 않는다. 41개 포인트를 직접 고르면 되는 앱이라
// GPS 로 얻는 이득이 권한 요청과 그에 딸린 문제들을 정당화하지 못했다.
// 결과적으로 이 앱이 요구하는 권한은 INTERNET 뿐이다.
edit('app/src/main/AndroidManifest.xml', '세로 고정 · cleartext 차단', src => {
  let s = src;

  if (!s.includes('android:screenOrientation')) {
    need(s, '<activity', '매니페스트 activity');
    s = s.replace('<activity', '<activity\n            android:screenOrientation="portrait"');
  }

  // 앱은 https 로컬 스킴 + https 원격만 쓴다. 평문은 필요 없다.
  s = s.replace(/android:usesCleartextTraffic="true"/, 'android:usesCleartextTraffic="false"');

  return s;
});

// ── 4. 다크 고정 · 상태바 색 ────────────────────────────────────
edit('app/src/main/res/values/styles.xml', '다크 테마 고정 · 상태바 #071A21', src => {
  let s = src;

  // DayNight 는 시스템 설정을 따라간다. 이 앱은 해도(nautical chart) 계열
  // 다크 전용이라 라이트 모드에서 상태바만 하얘지는 사고를 막는다.
  s = s.replace(/Theme\.AppCompat\.DayNight\.NoActionBar/g, 'Theme.AppCompat.NoActionBar');

  if (!s.includes('android:statusBarColor')) {
    need(s, '<item name="windowNoTitle">true</item>', 'styles.xml NoActionBar');
    s = s.replace('<item name="windowNoTitle">true</item>',
      `<item name="windowNoTitle">true</item>
        <item name="android:statusBarColor">#071A21</item>
        <item name="android:navigationBarColor">#071A21</item>
        <item name="android:windowLightStatusBar">false</item>`);
  }

  return s;
});

// ── 5. 앱 이름 확인 ─────────────────────────────────────────────
edit('app/src/main/res/values/strings.xml', '앱 이름', src => {
  const want = '워킹 조건';
  if (src.includes(`>${want}<`)) return null;
  return src
    .replace(/(<string name="app_name">)[^<]*(<\/string>)/, `$1${want}$2`)
    .replace(/(<string name="title_activity_main">)[^<]*(<\/string>)/, `$1${want}$2`);
});

console.log(`\n[patch] 변경 ${changed} · 이미 적용 ${skipped}`);
