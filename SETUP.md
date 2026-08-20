# 설치 가이드

한 번 설정하면 이후 손댈 일이 없도록 구성하는 절차입니다.
GitHub 계정만 있으면 되고 비용은 들지 않습니다.

---

## 0. 준비물 — 인증키 2개

먼저 발급받아 두세요. 승인에 시간이 걸리는 건 없습니다.

| 키 | 발급처 | 용도 | 필수 |
|---|---|---|---|
| `DATA_GO_KR_KEY` | [공공데이터포털](https://www.data.go.kr) | 조석 + 수온 | **필수** |
| `LAW_OC` | [국가법령정보 OPEN API](https://open.law.go.kr) | 금어기·금지체장 | 권장 |

`DATA_GO_KR_KEY` 는 포털 마이페이지 > 오픈API > 개발계정 의 **일반 인증키**입니다.
계정당 하나이지만 **API 마다 활용신청은 따로** 해야 합니다. 아래 둘 다 신청하세요
(개발단계 자동승인이라 즉시 발급됩니다).

- [조석예보(고, 저조) — 15156018](https://www.data.go.kr/data/15156018/openapi.do)
- [조위관측소 최신 관측데이터 — 15155508](https://www.data.go.kr/data/15155508/openapi.do)

> 구 바다누리(`khoa.go.kr/oceangrid`) OpenAPI 는 **2026-04-01 종료**됐습니다.
> 거기서는 이제 키가 발급되지 않습니다.

`LAW_OC`는 신청할 때 쓴 이메일의 **@ 앞부분**입니다. 예: `hongkildong@gmail.com` → `hongkildong`

`DATA_GO_KR_KEY`가 없으면 물때가 달 위상 근사로 떨어집니다. 서해에서 쓸 거면 사실상 필수입니다.

---

## 1. 저장소 만들기

GitHub에서 **New repository** → 이름은 아무거나 (예: `fishing-score`) → **Public** 선택.

> Public을 권하는 이유: Actions 실행 시간이 무제한입니다. Private은 월 2,000분
> 제한이 있는데, 이 워크플로는 하루 4회 × 몇 분이라 월 300분 안쪽이라 Private도
> 가능하긴 합니다. 다만 Public이 마음 편합니다. 인증키는 코드가 아니라
> Secrets에 들어가므로 공개해도 노출되지 않습니다.

파일을 이 구조대로 올립니다.

```
fishing-score/
├── index.html                루트 리다이렉트 → ./www/
├── www/index.html            프론트엔드 본체
├── khoa_api.py               포털 API 공용 계층
├── build_tides.py
├── collect_sst.py
├── sync_regulations.py
├── capacitor.config.json
├── package.json
├── scripts/                  앱 빌드 보조
├── assets/                   아이콘·스플래시 원본
├── README.md  ANDROID.md  CLAUDE.md
├── .nojekyll
├── .gitignore
└── .github/
    └── workflows/
        ├── data.yml          데이터 6시간 주기 갱신
        └── apk.yml           태그 → 서명 APK → Releases
```

`.nojekyll` 이 없으면 만들어 두세요. Pages 의 Jekyll 처리가 `_` 로 시작하는
경로를 무시하는 것을 막습니다.

터미널로 올리는 경우:

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<사용자명>/fishing-score.git
git push -u origin main
```

---

## 2. Secrets 등록

저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

이름을 정확히 이렇게 넣으세요. 오타가 나면 조용히 건너뜁니다.

- `DATA_GO_KR_KEY`
- `LAW_OC`

---

## 3. PAT 등록 — 이걸 빠뜨리면 60일 후 멈춥니다

**여기가 가장 중요합니다.** GitHub는 저장소에 60일간 활동이 없으면 예약
워크플로를 자동으로 비활성화합니다. 그런데 기본 `GITHUB_TOKEN`으로 봇이 만든
커밋은 이 "활동"으로 집계되지 않습니다. 즉 아무 조치 없이 두면 **두 달 뒤
데이터 갱신이 조용히 멈춥니다.**

해결책은 개인 토큰으로 푸시하게 만드는 것입니다.

1. GitHub 우상단 프로필 → **Settings** (계정 설정, 저장소 설정 아님)
2. 맨 아래 **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
3. **Generate new token**
   - Repository access: **Only select repositories** → 방금 만든 저장소
   - Permissions → Repository permissions → **Contents: Read and write**
   - Expiration: 최대치로 (1년). 만료 전에 GitHub가 메일로 알려줍니다.
4. 생성된 토큰 문자열 복사
5. 저장소 → Settings → Secrets → **New repository secret** → 이름 `PAT`, 값은 복사한 토큰

워크플로가 `secrets.PAT`이 있으면 그걸로, 없으면 기본 토큰으로 자동 전환하게
짜여 있어서, 등록하지 않아도 당장은 돌아갑니다. 다만 60일 시한부입니다.

---

## 4. Actions 권한 확인

저장소 → **Settings** → **Actions** → **General** → 맨 아래 **Workflow permissions**

**Read and write permissions** 선택 → Save.

이게 꺼져 있으면 워크플로가 데이터를 커밋하지 못하고 매번 실패합니다.

---

## 5. GitHub Pages 켜기

저장소 → **Settings** → **Pages**

- Source: **Deploy from a branch**
- Branch: **main** / **/ (root)** → Save

1~2분 뒤 주소가 나옵니다.

```
https://<사용자명>.github.io/fishing-score/
```

---

## 6. 첫 실행

저장소 → **Actions** 탭 → 좌측 **data** → 우측 **Run workflow** → 초록 버튼.

첫 실행에서 벌어지는 일:

- 수온 수집 — 1~2분
- 법령 별표 수집 — 30초
- 조석 캐시 — **1,200회만 받고 중단됩니다.** 정상입니다.

조석은 46개소 × 365일 = 약 16,800회 호출이 필요해서 한 번에 못 받습니다.
매 실행마다 1,200회씩 이어받으므로 **하루 4회 × 3~4일이면 한 해가 완성됩니다.**
그동안은 물때가 근사값으로 표시되고, 완성되면 자동으로 실측 기반으로 바뀝니다.

기다리기 싫으면 로컬에서 한 번에 받아 커밋하면 됩니다.

```bash
export DATA_GO_KR_KEY="공공데이터포털_일반_인증키"
python build_tides.py            # 수 시간 소요
git add data .cache && git commit -m "tide cache" && git push
```

---

## 7. 안드로이드 앱 — 키스토어 만들기

APK 에 서명할 키가 필요합니다. **최초 1회만** 하면 됩니다.

```bash
powershell -ExecutionPolicy Bypass -File scripts\make-keystore.ps1
```

비밀번호를 정하면 `shorefishing.keystore` 와 `shorefishing.keystore.b64` 가 생깁니다.
스크립트가 출력하는 대로 **Secrets 4개**를 등록하세요.

| 시크릿 | 값 |
|---|---|
| `KEYSTORE_B64` | `.b64` 파일 내용 전체 |
| `KEYSTORE_PASSWORD` | 방금 정한 비밀번호 |
| `KEY_ALIAS` | `shorefishing` |
| `KEY_PASSWORD` | 같은 비밀번호 |

**이 파일과 비밀번호를 잃어버리면 되돌릴 수 없습니다.** 기존 설치본에
업데이트를 못 올려서 지인들이 앱을 지우고 다시 깔아야 합니다.
등록이 끝나면 `.b64` 는 지우고 키스토어는 안전한 곳에 백업하세요.
둘 다 `.gitignore` 에 들어 있어 커밋되지 않습니다.

> 시크릿을 등록하지 않아도 워크플로는 **디버그 APK** 로 빌드합니다.
> 먼저 동작을 확인하고 싶으면 이 단계를 건너뛰고 8번으로 가세요.
> 다만 디버그 서명은 빌드마다 달라져 덮어 설치가 안 됩니다.

---

## 8. APK 빌드

```bash
git tag v1.0.0
git push origin v1.0.0
```

Actions → **apk** 워크플로가 돌고 5~10분 뒤 **Releases** 에 APK 가 올라옵니다.
태그 없이 시험만 해보려면 Actions 탭 → apk → **Run workflow** 로 돌리면
Releases 대신 **Artifacts** 에 올라옵니다.

### 지인에게 배포

릴리스 링크를 보내면 됩니다. 받는 쪽 순서:

1. 링크에서 APK 다운로드
2. "이 출처의 앱 설치 허용" 요청이 뜨면 허용 (브라우저별 최초 1회)
3. 설치 → "안전하지 않은 앱" 경고에서 그대로 설치

Play Protect 경고는 정상입니다. Play 스토어에 등록된 인증서가 아니기 때문입니다.
미리 안내해 두세요.

**업데이트는 자동이 아닙니다.** 새 APK 를 받아 덮어 설치해야 합니다.
앱 상단 툴바에 새 버전이 있으면 `v1.0.0 → v1.0.1` 로 표시됩니다.

---

## 9. 웹으로도 쓰기 (선택)

앱을 깔지 않고 브라우저로 쓰려면 Pages 주소를 홈 화면에 추가하면 됩니다.

**Android Chrome** — 주소 열기 → ⋮ → 홈 화면에 추가
**iOS Safari** — 주소 열기 → 공유 → 홈 화면에 추가

주소창 없이 뜨지만 **오프라인은 안 됩니다.** 현장에서 쓸 거면 APK 를 쓰세요.

---

## 이후 자동으로 도는 것

| 주기 | 작업 |
|---|---|
| 6시간마다 (KST 03·09·15·21시) | 연안 수온 갱신 |
| 6시간마다 | 법령 시행일 확인 → 바뀌었을 때만 별표 재수집 |
| 6시간마다 | 조석 캐시 미완성이면 1,200회씩 이어받기 |
| 11월부터 | 내년치 조석을 미리 채우기 시작 |

연초에 물때가 비는 일이 없도록 11월부터 다음 해를 미리 받습니다.
파일이 이미 완성돼 있으면 아무것도 하지 않으므로 매번 돌아도 부담이 없습니다.

---

## 고장났을 때 알아채는 법

**앱 상단 피드 배지가 1차 경보입니다.**

| 배지 | 뜻 | 조치 |
|---|---|---|
| `LIVE` | 정상 | — |
| `갱신중단 N일` | 수집기가 죽은 지 N일 | Actions 탭에서 로그 확인 |
| `근사` / `씨드` | 데이터 파일 자체가 없음 | 워크플로를 아직 안 돌렸거나 실패 |
| `실패` | Open-Meteo 호출 실패 | 대개 일시적. 새로고침 |

수온은 12시간, 법령은 150일이 지나면 자동으로 `갱신중단`으로 바뀝니다.
수집기가 죽었는데 오래된 값을 정상인 척 보여주는 게 가장 위험해서 넣은 장치입니다.

**GitHub가 메일로도 알려줍니다.** 예약 워크플로가 실패하면 저장소 소유자에게
자동으로 실패 알림이 갑니다. 이 메일이 오면 Actions 탭을 열어보세요.

---

## 자주 나는 문제

**커밋 단계에서 403**
4번(Workflow permissions)을 안 했거나 PAT 권한에 Contents: Write가 빠진 경우입니다.

**수온이 계속 `근사`**
`DATA_GO_KR_KEY` 시크릿 이름 오타이거나, **15155508 활용신청을 안 한** 경우입니다.
로그에 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 가 찍히면 후자입니다.
Actions 로그의 "수온 수집" 단계를 펼쳐보면 실패 사유가 찍힙니다.

**법규가 계속 `씨드`**
`LAW_OC`를 등록하지 않았거나 이메일 전체를 넣은 경우입니다. @ 앞부분만 넣으세요.

**조석이 며칠째 미완성**
Actions 요약에 진행률이 찍힙니다. 개발계정 일일 한도(10,000회)에
걸렸을 수 있습니다. 워크플로의 `--budget 1200`을 낮추면 더 천천히, 안전하게 받습니다.

**예약 실행이 늦거나 건너뜀**
GitHub 스케줄러는 부하에 따라 5~30분 지연되고 드물게 한 번씩 건너뜁니다.
6시간 주기라 실질적인 영향은 없습니다.

**1년 뒤 PAT 만료**
GitHub가 만료 전에 메일을 보냅니다. 3번 과정을 다시 해서 시크릿 값만 바꾸면 됩니다.
이게 유일하게 사람 손이 필요한 정기 작업입니다.
