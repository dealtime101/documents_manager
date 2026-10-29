# Prepares packaging\tesseract\ : tesseract.exe, its DLLs and the language data (eng, fra, osd) that the executable carries.
# The official Windows build of Tesseract (UB Mannheim, Apache-2.0) is downloaded, checked against a pinned SHA-256, installed
# silently into build\ (never into the system) and copied; nothing is left installed on the machine.
param([string]$From = "",  # an existing Tesseract folder to copy from (skips the download and the installer)
      [string]$Sha256 = "")  # the SHA-256 the installer must have, while none is pinned below
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "packaging\tesseract"
if (Test-Path (Join-Path $out "tesseract.exe")) { Write-Host "Tesseract already prepared in $out"; exit 0 }
$work = Join-Path $root "build\tesseract-src"
$install = $From
if (-not $install) {
  $work = Join-Path $root "build\tesseract-src"
  New-Item -ItemType Directory -Force -Path $work | Out-Null
  $installer = Join-Path $work "tesseract-setup.exe"
  $url = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
  $pinned = ""  # the installer's SHA-256 in lower case, once checked against a source you trust (see the error below)
  $expected = if ($Sha256) { $Sha256.ToLower() } else { $pinned }
  Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
  $actual = (Get-FileHash $installer -Algorithm SHA256).Hash.ToLower()
  # No hash to compare with is a failure, not a pass: the installer is about to be RUN and shipped inside the product
  if (-not $expected) { throw "No pinned SHA-256 for the Tesseract installer. This download is $actual : compare it with a source you trust, then put it in `$pinned` in this script (or pass -Sha256). Nothing was run." }
  if ($actual -ne $expected) { throw "Tesseract installer hash mismatch: expected $expected, got $actual" }
  Write-Host "installer sha256: $actual"
  $install = Join-Path $work "install"
  # NSIS: /D= must come last and unquoted, so the arguments go in as ONE string
  Start-Process -FilePath $installer -ArgumentList "/S /D=$install" -Wait
}
New-Item -ItemType Directory -Force -Path (Join-Path $out "tessdata") | Out-Null
Copy-Item (Join-Path $install "tesseract.exe") $out
Copy-Item (Join-Path $install "*.dll") $out
foreach ($lang in "eng", "osd") { Copy-Item (Join-Path $install "tessdata\$lang.traineddata") (Join-Path $out "tessdata") }
Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/tesseract-ocr/tessdata_best/raw/main/fra.traineddata" -OutFile (Join-Path $out "tessdata\fra.traineddata")
Copy-Item (Join-Path $install "doc\LICENSE") (Join-Path $out "LICENSE-Tesseract.txt") -ErrorAction SilentlyContinue
Write-Host "Prepared $out"
