Param(
    [switch]$Clean
)

Set-StrictMode -Version Latest
Push-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Definition)

if(-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)){
    Write-Error "PyInstaller not found. Install it in the active Python environment: pip install pyinstaller"
    Pop-Location
    exit 1
}

# Resolve repo root and spec path relative to the script location.
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Resolve-Path -LiteralPath (Join-Path $scriptDir '..') | ForEach-Object { $_.Path }
$distPath = Join-Path $repoRoot 'dist'
$workPath = Join-Path $scriptDir 'build'
$spec = Join-Path $repoRoot 'Trading Strategies\Iron Condor\ic-v2.spec'
$spec = Resolve-Path -LiteralPath $spec -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }
if(-not $spec){
    Write-Error "Spec file not found: Trading Strategies\\Iron Condor\\ic-v2.spec"
    Pop-Location
    exit 1
}

New-Item -ItemType Directory -Force -Path $distPath | Out-Null
New-Item -ItemType Directory -Force -Path $workPath | Out-Null

Write-Output "Building ic-v2 as one-file bundle into repo-root dist (this may take a few minutes)..."
$buildArgs = @('--distpath',$distPath,'--workpath',$workPath,$spec)
if($Clean){
    $buildArgs = @('--clean','--distpath',$distPath,'--workpath',$workPath,$spec)
}

Write-Output "Running PyInstaller with args: $buildArgs"
& pyinstaller @buildArgs
$rc = $LASTEXITCODE
if($rc -ne 0){
    Write-Error "PyInstaller failed with exit code $rc"
    Pop-Location
    exit $rc
}

Write-Output "Build finished. Output in ./dist/ic-v2.exe"
Pop-Location
exit 0
