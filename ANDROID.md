# ANDROID.md — 안드로이드 앱

`www/index.html` 을 Capacitor 로 감싸 APK 로 만들어 본인·지인에게 사이드로딩한다.
Play 스토어 등록 없음. 전제 컨텍스트는 `CLAUDE.md` 참조.

**이 문서는 이미 구현된 상태를 기술한다.** 작업 지시서가 아니라 설계 기록이다.
남은 사람 손이 필요한 일은 8절에만 있다.

---

## 0. 왜 Capacitor인가

| 방식 | 판정 | 사유 |
|---|---|---|
| PWA 홈화면 추가 | 부족 | APK 아님. 지인 배포 불가. 오프라인 제어 약함 |
| TWA (Bubblewrap) | 부적합 | 사이트가 항상 온라인이어야 함 |
| **Capacitor** | **채택** | 진짜 APK, 로컬 에셋 번들, 네이티브 플러그인 |
| React Native 재작성 | 과잉 | 동작하는 단일 HTML 을 버릴 이유 없음 |

**결정적 이유는 오프라인이다.** 갯바위·방파제는 신호가 약하거나 없다.
현장에서 앱이 안 뜨면 존재 이유가 없다.

---

## 1. 확정 사양

| 항목 | 값 |
|---|---|
| applicationId | `kr.local.shorefishing` |
| 앱 이름 | 워킹 조건 |
| Capacitor | 7.x |
| minSdk / targetSdk | 26 (Android 8.0) / 35 |
| JDK | **21** (Capacitor 7 요구. 17 로는 AGP 가 뜨지 않는다) |
| 방향 | 세로 고정 |
| 테마 | 다크 고정 (`Theme.AppCompat.NoActionBar`, DayNight 아님) |
| 위치 권한 | `ACCESS_COARSE_LOCATION` 만 (FINE 은 매니페스트에서 제거) |
| 배포 | GitHub Releases 에 서명된 APK |

---

## 2. 저장소 구조

```
repo/
├── index.html                루트 리다이렉트 → ./www/ (Pages 주소 유지용)
├── www/
│   ├── index.html            앱과 웹이 공유하는 단일 파일
│   └── fonts/                빌드 때 npm 에서 복사 (.gitignore)
├── data/                     data.yml 이 갱신. Pages 가 서빙
├── assets/                   아이콘·스플래시 원본 PNG
├── scripts/
│   ├── bundle-fonts.mjs      npm woff2 → www/fonts/
│   ├── inject-config.mjs     APK 안 index.html 에 Pages 주소·버전 주입
│   ├── patch-android.mjs     생성된 android/ 에 이 앱의 요구사항 적용
│   ├── make_assets.py        아이콘·스플래시 생성 (순수 파이썬, 의존성 없음)
│   └── make-keystore.ps1     서명 키스토어 생성 (최초 1회)
├── capacitor.config.json
├── package.json
├── build_tides.py  collect_sst.py  sync_regulations.py
└── .github/workflows/
    ├── data.yml              6시간 주기 데이터 갱신
    └── apk.yml               태그 → 서명 APK → Releases
```

### android/ 를 커밋하지 않는 이유

`npx cap add android` 결과물은 **저장소에 없다.** CI 가 매 빌드마다 새로 만들고
`scripts/patch-android.mjs` 가 같은 패치를 다시 입힌다.

커밋해 두면 `cap sync` 와 손으로 고친 내용이 어긋나고, 어느 쪽이 진짜인지
알 수 없어진다. 안드로이드 쪽을 바꿀 일이 생기면 `patch-android.mjs` 를 고친다.
그 파일이 안드로이드 설정의 단일 출처다.

`capacitor.config.ts` 대신 **`.json`** 을 쓴다. TypeScript 툴체인 없이도
CLI 가 그대로 읽는다.

---

## 3. 데이터 계층 — 앱과 웹의 유일한 분기

```js
const NATIVE = !!(window.Capacitor && window.Capacitor.isNativePlatform?.());
const dataURL = f => (NATIVE && hasRemote) ? `${CFG.REMOTE}/data/${f}` : WEB_DATA + f;
```

`CFG.REMOTE` 는 소스에 `__PAGES_URL__` 자리표시자로 있고, **`cap sync` 이후**
`inject-config.mjs` 가 APK 안에 복사된 사본만 치환한다. 원본 `www/index.html`
은 건드리지 않으므로 저장소가 더러워지지 않고, 웹에서는 자리표시자가 남아
상대경로(`../data/`) 폴백이 그대로 동작한다.

CI 는 `GITHUB_REPOSITORY` 에서 Pages 주소를 자동으로 만든다. 저장소를 옮겨도
고칠 데가 없다. 다른 주소를 쓰려면 저장소 변수 `PAGES_URL` 을 넣는다.

### 캐시 정책 — 파일마다 다르다

| 파일 | 크기 | 저장소 | 정책 |
|---|---|---|---|
| `tide-<YEAR>.json` | ~2MB | Filesystem | **연도별 영구.** 한 번 받으면 그 해 내내 재다운로드 없음. 해가 바뀌면 지난해 파일 삭제 |
| `om-cache.json` | ~1MB | Filesystem | Open-Meteo 응답. 6시간 이내면 재요청 안 함 |
| `sst-latest.json` | ~10KB | Preferences | 매 실행 시도, 실패하면 캐시 |
| `regulations.json` | ~5KB | Preferences | 24시간마다 시도, 실패하면 캐시 |

`localStorage` 는 쓰지 않는다. 웹에서는 캐시 계층 전체가 no-op 이다.

### 부팅 순서

```
1. 캐시에서 즉시 로드 → 렌더        (오프라인이어도 뜬다)
2. 네트워크 상태 확인
3. 온라인이면 백그라운드 갱신 → 재렌더
4. 실패해도 조용히 캐시 유지. 배지로만 표시
```

네트워크가 돌아오거나(`networkStatusChange`) 앱으로 복귀하면(`appStateChange`)
다시 시도한다. **절대 네트워크를 기다리며 빈 화면을 띄우지 않는다.**

### 캐시가 만든 함정 하나 — `omOffset()`

Open-Meteo 의 `hourly` 배열은 **오늘 00시부터 시작한다**는 전제로 인덱싱된다.
날짜가 바뀐 캐시를 그대로 쓰면 24칸씩 밀린 값을 조용히 보게 된다.
파고가 어제 값인데 오늘인 척하는 것이라 가장 나쁜 종류의 버그다.

그래서 `hourly.time[0]` 과 오늘 자정의 차이를 `DATA.omOff` 로 보정한다.
범위를 벗어나면 `null` → 기본값으로 떨어지므로 조용한 오답 대신 명시적 폴백이 된다.

### 신선도 검사는 캐시에도 적용된다

수온 12시간, 법령 150일. `markStale()` 은 네트워크 응답이든 캐시든 똑같이 검사한다.
**오프라인이 신선도 검사의 면제부가 되면 안 된다.** 이 로직을 제거하지 말 것.

---

## 4. KHOA 를 앱에서 직접 부르지 않는 이유

`CapacitorHttp` 로 CORS 가 뚫리므로 기술적으로는 가능하다. 하지만 하지 않는다.

- **인증키가 APK 에 박힌다.** 디컴파일하면 그대로 나온다. 지인 배포라도 위험
- 조석은 앱에서 계산할 게 아니라 미리 만들어 둘 데이터다
- Actions 가 이미 갱신하고 있어 중복

"수집기 → 정적 JSON → 앱이 읽기" 구조를 유지한다.
**인증키가 없는 Open-Meteo 만** 앱에서 직접 부른다.

---

## 5. 오프라인 폰트

CDN 폰트는 갯바위에서 로드되지 않는다. 계기판 서체가 이 앱의 정체성이라
`bundle-fonts.mjs` 가 npm 패키지의 woff2 를 `www/fonts/` 로 복사해 APK 에 담는다.

`www/index.html` 은 번들 폰트를 1순위, CDN 폰트를 2순위로 선언한다.

```css
--sans:'PretendardBundled','Pretendard Variable',Pretendard,-apple-system,...;
```

`www/fonts/` 는 `.gitignore` 에 있으므로 웹(Pages)에서는 404 → 자동으로 CDN 으로
폴백된다. 파일을 포크하지 않고 양쪽을 다 만족시키는 지점이다.

---

## 6. 네이티브 기능

### 6-1. 화면 꺼짐 방지 — 구현됨

`@capacitor-community/keep-awake` 대신 **Screen Wake Lock API** 를 쓴다.
WebView 표준이라 서드파티 플러그인이 필요 없고, 웹에서도 그대로 동작한다.
Capacitor 가 `https://localhost` 로 서빙하므로 보안 컨텍스트 요건도 만족한다.

화면이 가려지면 OS 가 락을 자동 해제하므로 `visibilitychange` 에서 재획득한다.
툴바에서 끌 수 있고 설정은 Preferences 에 남는다.

### 6-2. GPS 최근접 포인트 — 구현됨

앱 실행 시 41개 포인트 중 최근접을 자동 선택한다. **30km 이상 떨어져 있으면
자동 선택하지 않고** 거리만 표시한다. 권한을 거부해도 앱은 정상 동작한다.

정밀 위치는 필요 없으므로 `patch-android.mjs` 가 `ACCESS_FINE_LOCATION` 을
`tools:node="remove"` 로 걷어낸다. Geolocation 플러그인이 병합해 넣는 것을 되돌리는 것이다.

### 6-3. 업데이트 알림 — 구현됨

사이드로딩이라 자동 업데이트가 없다. GitHub Releases API 로 최신 태그를 보고
현재 버전과 다르면 툴바에 `v1.0.0 → v1.0.1` 을 띄운다. 설치는 사용자가 한다.
**자동 업데이터는 만들지 않는다 — 개인용 앱에 과잉이다.**

### 6-4. 출조 알림 · 즐겨찾기 — 미구현 (선택)

원래 명세에서 선택 항목이었고 이번 범위에서 뺐다. 넣으려면
`@capacitor/local-notifications` 를 추가하고 앱을 열 때 다음 알림을 예약하는
방식으로 한다. 백그라운드 실행이나 배터리 최적화 예외 요청은 넣지 말 것.

---

## 7. 빌드

로컬에 Android SDK 가 없어도 된다. ubuntu 러너에 SDK·JDK·Node 가 이미 있다.

```
checkout → npm install → bundle-fonts → cap add android → cap sync
  → @capacitor/assets generate → inject-config → patch-android
  → 키스토어 복원 → gradlew assembleRelease → Releases 업로드
```

`inject-config` 가 `cap sync` **뒤에** 오는 순서가 중요하다. sync 가 `www/` 를
`android/app/src/main/assets/public/` 로 복사하므로, 그 전에 주입하면 원본이 더럽혀진다.

**키스토어 시크릿이 없으면 디버그 APK 로 빌드한다.** 첫 스모크 테스트는 되지만
디버그 서명은 빌드마다 달라져 기존 설치본을 덮어쓰지 못한다. 릴리스 전에 키스토어를 만든다.

로컬에서 빌드하려면 Node 20 + JDK 21 + Android SDK 를 깔고:

```bash
npm install
npm run prepare:android
npm run build:debug
```

---

## 8. 남은 사람 손 — 이 4가지뿐

1. **GitHub 저장소 생성 + 푸시** (`SETUP.md` 1절)
2. **Secrets 등록** — `KHOA_KEY` `LAW_OC` `NIFS_KEY` `PAT` (`SETUP.md` 2·3절)
3. **키스토어 생성 + 시크릿 4개 등록**

   ```bash
   powershell -ExecutionPolicy Bypass -File scripts\make-keystore.ps1
   ```

   `KEYSTORE_B64` `KEYSTORE_PASSWORD` `KEY_ALIAS` `KEY_PASSWORD`

   **키스토어를 잃어버리면 되돌릴 수 없다.** 기존 설치본에 업데이트를 못 올려서
   지인들이 앱을 지우고 다시 깔아야 한다. 만든 직후 안전한 곳에 백업할 것.

4. **태그 푸시**

   ```bash
   git tag v1.0.0 && git push origin v1.0.0
   ```

---

## 9. 검증 체크리스트

CI 없이 로컬에서 확인한 항목:

- [x] 5월에 감성돔(porgy)을 고르면 0점 + `금어기` 스탬프
- [x] 동해 포인트에서 주꾸미(webfoot)가 `해역 밖`으로 제외
- [x] 서해/동해 물때 가중치가 다르게 표시 (0.229 vs 0.071, 약 3.2배)
- [x] 정적 JSON 이 없어도 앱이 뜨고 점수가 나온다 (근사·씨드 폴백)
- [x] 웹에서 `../data/` 상대경로가 올바르게 해석된다
- [x] 폰트 404 가 CDN 폴백을 막지 않는다

실기기에서 확인할 항목:

- [ ] 비행기 모드에서 앱이 뜨고 캐시된 데이터로 점수가 나온다
- [ ] 조석 JSON 을 두 번째 실행에서 재다운로드하지 않는다
- [ ] 위치 권한을 거부해도 앱이 정상 동작한다
- [ ] 정조 시각으로 슬라이더를 옮기면 물때 팩터가 급락한다 (조석 JSON 필요)
- [ ] 수온이 12시간 이상 오래되면 `갱신중단` 배지가 뜬다
- [ ] 세로 고정, 다크 고정, 상태바 색이 배경과 일치
- [ ] 실기기 설치·실행

---

## 10. 주의

- `score` `conditions` `tideAt` `inClosed` 는 **순수 함수로 유지한다.**
  네이티브 호출을 이 안에 섞지 말 것. 백테스트 가능성이 이 프로젝트의 확장 경로다.
  네이티브 API 는 브리지 블록과 8절 블록에만 있다.
- 웹과 앱이 **같은 `www/index.html` 을 공유한다.** 분기는 `NATIVE` 하나뿐이다.
  파일을 포크하지 말 것.
- 계정·로그인·서버를 만들지 않는다. 전부 로컬 + 정적 JSON.
- 구명조끼 의무, 금어기 확인 문구는 어떤 리팩터에서도 남긴다.
