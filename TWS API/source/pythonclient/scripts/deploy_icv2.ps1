Set-StrictMode -Version Latest
Push-Location -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Definition)

Write-Output "Starting build+deploy for ic-v2..."

$buildScript = Join-Path (Get-Location) 'build_icv2.ps1'
if(-not (Test-Path $buildScript)){
    Write-Error "Build script not found: $buildScript"
    Pop-Location
    exit 1
}

& $buildScript -Clean
if($LASTEXITCODE -ne 0){
    Write-Error "Build failed. Aborting deploy."
    Pop-Location
    exit $LASTEXITCODE
}

$repoRoot = Resolve-Path -LiteralPath (Join-Path (Get-Location) '..') | ForEach-Object { $_.Path }
$outExe = Join-Path $repoRoot 'dist\ic-v2.exe'
if(-not (Test-Path $outExe)){
    Write-Error "Expected build output not found: $outExe"
    Pop-Location
    exit 1
}

$deployDir = Join-Path $repoRoot 'dist\icv-2'
$sourceConfig = Join-Path $repoRoot 'Trading Strategies\Iron Condor\ic.json'
if(-not (Test-Path $sourceConfig)){
    Write-Error "Source config file not found: $sourceConfig"
    Pop-Location
    exit 1
}

if(Test-Path $deployDir){
    Try {
        Remove-Item -Recurse -Force $deployDir -ErrorAction Stop
    } Catch {
        Write-Warning "Could not remove existing deploy dir $deployDir; reusing existing directory."
    }
}
New-Item -ItemType Directory -Force -Path $deployDir | Out-Null

Copy-Item -Path $outExe -Destination (Join-Path $deployDir 'ic-v2.exe') -Force
Copy-Item -Path $sourceConfig -Destination (Join-Path $deployDir 'ic.json') -Force

$manifest = [PSCustomObject]@{
    name = 'icv-2'
    version = '1.0.0'
    deployed = (Get-Date).ToString('o')
    files = Get-ChildItem -Path $deployDir -File | Select-Object Name,Length
}

$manifest | ConvertTo-Json -Compress | Out-File -Encoding utf8 (Join-Path $deployDir 'deploy.json')

Write-Output "Deployed ic-v2 -> $deployDir"
Pop-Location
exit 0
