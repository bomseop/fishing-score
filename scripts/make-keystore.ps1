<#
.SYNOPSIS
  APK 서명용 키스토어를 만들고 GitHub 시크릿에 넣을 값을 출력한다. 최초 1회만.

.DESCRIPTION
  이 파일과 비밀번호를 잃어버리면 기존 설치본에 업데이트를 올릴 수 없다.
  지인들이 앱을 지우고 다시 깔아야 한다. 만든 직후 안전한 곳에 백업할 것.
  .gitignore 에 이미 들어 있으므로 저장소에는 올라가지 않는다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\make-keystore.ps1
#>
param(
  [string]$Out   = "shorefishing.keystore",
  [string]$Alias = "shorefishing",
  [int]$Days     = 10000
)

$ErrorActionPreference = "Stop"

# ── keytool 찾기 ──────────────────────────────────────────────
$keytool = $null
$cmd = Get-Command keytool -ErrorAction SilentlyContinue
if ($cmd) { $keytool = $cmd.Source }
if (-not $keytool -and $env:JAVA_HOME) {
  $p = Join-Path $env:JAVA_HOME "bin\keytool.exe"
  if (Test-Path $p) { $keytool = $p }
}
if (-not $keytool) {
  $roots = @("$env:ProgramFiles\Java", "$env:ProgramFiles\Eclipse Adoptium",
             "${env:ProgramFiles(x86)}\Java", "$env:LOCALAPPDATA\Programs\Eclipse Adoptium")
  foreach ($r in $roots) {
    if (Test-Path $r) {
      $found = Get-ChildItem $r -Recurse -Filter keytool.exe -ErrorAction SilentlyContinue |
               Select-Object -First 1
      if ($found) { $keytool = $found.FullName; break }
    }
  }
}
if (-not $keytool) {
  Write-Error "keytool 을 찾지 못했습니다. JDK 또는 JRE 를 설치한 뒤 다시 실행하세요."
}
Write-Host "keytool : $keytool"

if (Test-Path $Out) {
  Write-Error "$Out 이(가) 이미 있습니다. 덮어쓰면 기존 설치본에 업데이트를 못 올립니다. 먼저 백업하고 옮기세요."
}

# ── 비밀번호 ──────────────────────────────────────────────────
Write-Host ""
Write-Host "키스토어 비밀번호를 정하세요 (6자 이상). 잊으면 복구 방법이 없습니다."
$sec1 = Read-Host "비밀번호" -AsSecureString
$sec2 = Read-Host "다시 입력" -AsSecureString
$p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec1))
$p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec2))
if ($p1 -ne $p2)      { Write-Error "비밀번호가 일치하지 않습니다." }
if ($p1.Length -lt 6) { Write-Error "6자 이상이어야 합니다." }

# ── 생성 ──────────────────────────────────────────────────────
& $keytool -genkeypair -v `
  -keystore $Out -storetype PKCS12 `
  -alias $Alias -keyalg RSA -keysize 2048 -validity $Days `
  -storepass $p1 -keypass $p1 `
  -dname "CN=Shore Fishing Condition, OU=Personal, O=Personal, L=Seoul, C=KR"
if ($LASTEXITCODE -ne 0) { Write-Error "keytool 실패 (exit $LASTEXITCODE)" }

$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $Out)))
$b64Path = "$Out.b64"
Set-Content -Path $b64Path -Value $b64 -NoNewline -Encoding ascii

Write-Host ""
Write-Host "생성 완료 : $Out"
Write-Host ""
Write-Host "─────────────────────────────────────────────────────────"
Write-Host " GitHub → Settings → Secrets and variables → Actions"
Write-Host " 아래 4개를 Repository secret 으로 등록하세요."
Write-Host "─────────────────────────────────────────────────────────"
Write-Host "  KEYSTORE_B64       → $b64Path 의 내용 전체"
Write-Host "  KEYSTORE_PASSWORD  → 방금 정한 비밀번호"
Write-Host "  KEY_ALIAS          → $Alias"
Write-Host "  KEY_PASSWORD       → 방금 정한 비밀번호 (같은 값)"
Write-Host ""
Write-Host "등록이 끝나면 $b64Path 는 지우세요. $Out 은 안전한 곳에 백업하세요."
Write-Host "둘 다 .gitignore 에 들어 있어 커밋되지 않습니다."
