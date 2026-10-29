# Prepares packaging\tesseract\ : tesseract.exe, its DLLs and the language data (eng, fra, osd) that the executable carries.
# The official Windows build of Tesseract (UB Mannheim, Apache-2.0) is downloaded, checked against a pinned SHA-256, installed
# silently into a folder of build\ (the files are not put in Program Files) and copied. The NSIS installer is run, not unpacked and
# not uninstalled: it may still leave an uninstall entry in the registry or shortcuts on the build machine. Use a throwaway build
# machine or CI runner, or pass -From with a Tesseract folder you already have to skip the installer.
param([string]$From = "",  # an existing Tesseract folder to copy from (skips the installer; language files that are the pinned ones are taken from it, the others are downloaded)
      [string]$Sha256 = "")  # the SHA-256 the installer must have, while none is pinned below
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Windows PowerShell 5.1 draws the progress bar of Invoke-WebRequest so slowly that a 50 MB download takes minutes
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "packaging\tesseract"
# "Already prepared" means EVERYTHING is there: a run that stopped after copying tesseract.exe must start again, not count as done
$needed = "tesseract.exe", "tessdata\eng.traineddata", "tessdata\osd.traineddata", "tessdata\fra.traineddata"
$missing = @($needed | Where-Object { -not (Test-Path (Join-Path $out $_)) })
$dlls = @(Get-ChildItem -Path $out -Filter "*.dll" -ErrorAction SilentlyContinue)
if ($missing.Count -eq 0 -and $dlls.Count -gt 0) { Write-Host "Tesseract already prepared in $out"; exit 0 }
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
  $proc = Start-Process -FilePath $installer -ArgumentList "/S /D=$install" -Wait -PassThru
  # a refused or failed install (UAC, rights) must stop here with its own message, not later on a Copy-Item of a missing file
  if ($proc.ExitCode -ne 0) { throw "The Tesseract installer failed (exit code $($proc.ExitCode)). Nothing was copied." }
  if (-not (Test-Path (Join-Path $install "tesseract.exe"))) { throw "The Tesseract installer finished but $install has no tesseract.exe. Nothing was copied." }
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
  # a file of the folder given with -From is taken when it IS the pinned one (same blob id): that build can then run offline
  $local = Join-Path $install "tessdata\$lang.traineddata"
  if ((Test-Path $local) -and ((Get-GitBlobId $local) -eq $blobIds[$lang])) { Copy-Item $local $target }
  else { Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/$tessdataCommit/$lang.traineddata" -OutFile $target }
  $blob = Get-GitBlobId $target
  if ($blob -ne $blobIds[$lang]) { Remove-Item $target; throw "$lang.traineddata does not match the pinned file: expected $($blobIds[$lang]), got $blob" }
}
# The licence texts travel with the binaries (Apache-2.0 asks for them): every LICENSE*/NOTICE* file of the install's doc\ folder is
# copied, and a package without any is a failure, not a silent omission.
$licences = @(Get-ChildItem -Path (Join-Path $install "doc") -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(LICENSE|LICENCE|NOTICE|COPYING)' })
if ($licences.Count -eq 0) { throw "No LICENSE/NOTICE file in $(Join-Path $install 'doc'): Tesseract must not be redistributed without its licence text." }
foreach ($file in $licences) { Copy-Item $file.FullName (Join-Path $out ("LICENSE-Tesseract-" + $file.Name + ".txt")) }
Write-Host "Prepared $out"
