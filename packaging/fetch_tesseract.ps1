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
# The language data: ALL of it from one pinned commit of tessdata_best (tag 4.1.0), not the installer's mix and not the moving main
# branch, and each file checked against its git blob id (GitHub's contents API gives it: GET /repos/tesseract-ocr/tessdata_best/contents/<file>?ref=<commit>).
$tessdataCommit = "e2aad9b983032bb1beff9133104a67cdbb87ca4d"
$blobIds = @{ eng = "176dc3220de7db34d3b3aecbfa42043a6038348b"; osd = "527457ca8f8fe1fda7c2f88bce3c0e4be12be9d0"; fra = "f73e7dec0669dbac6443d8f83054b8b2a3146729" }
function Get-GitBlobId([string]$path) {
  $bytes = [IO.File]::ReadAllBytes($path)
  $header = [Text.Encoding]::ASCII.GetBytes("blob $($bytes.Length)" + [char]0)
  $sha1 = [Security.Cryptography.SHA1]::Create()
  $sha1.TransformBlock($header, 0, $header.Length, $null, 0) | Out-Null
  $sha1.TransformFinalBlock($bytes, 0, $bytes.Length) | Out-Null
  return (($sha1.Hash | ForEach-Object { $_.ToString("x2") }) -join "")
}
foreach ($lang in $blobIds.Keys) {
  $target = Join-Path $out "tessdata\$lang.traineddata"
  Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/$tessdataCommit/$lang.traineddata" -OutFile $target
  $blob = Get-GitBlobId $target
  if ($blob -ne $blobIds[$lang]) { Remove-Item $target; throw "$lang.traineddata does not match the pinned file: expected $($blobIds[$lang]), got $blob" }
}
Copy-Item (Join-Path $install "doc\LICENSE") (Join-Path $out "LICENSE-Tesseract.txt") -ErrorAction SilentlyContinue
Write-Host "Prepared $out"
