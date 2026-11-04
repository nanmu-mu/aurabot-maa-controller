#requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Build local assets only. No GitHub calls, production installation, or game execution.
$releaseRoot = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $releaseRoot 'dist'
$sourceStage = Join-Path $outputDir 'source-stage\aurabot-maa-controller'
$moduleStage = Join-Path $outputDir 'maa-controller'
$package = Get-Content -LiteralPath (Join-Path $releaseRoot 'package.json') -Raw | ConvertFrom-Json
$version = $package.version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a three-part release version' }
$moduleZip = Join-Path $outputDir "aurabot-maa-controller-$version.zip"
$sourceZip = Join-Path $outputDir "aurabot-maa-controller-$version-source.zip"
$checksumFile = Join-Path $outputDir 'SHA256SUMS.txt'
foreach ($target in @($sourceStage, $moduleStage, $moduleZip, $sourceZip, $checksumFile)) {
    if (Test-Path -LiteralPath $target) { throw "Build output already exists; archive it before rebuilding: $target" }
}

$sourceFiles = @(Get-Content -LiteralPath (Join-Path $releaseRoot 'release-files.json') -Raw | ConvertFrom-Json)
if ($sourceFiles.Count -ne @($sourceFiles | Sort-Object -Unique).Count) { throw 'Duplicate source entries' }
foreach ($name in $sourceFiles) {
    if ([IO.Path]::IsPathRooted($name) -or ($name -split '[/\\]') -contains '..') { throw "Invalid source entry: $name" }
    $fullName = [IO.Path]::GetFullPath((Join-Path $releaseRoot $name))
    if (-not $fullName.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Source path escaped project root' }
    $entry = Get-Item -LiteralPath $fullName
    if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Source entry must be a regular file: $name" }
}

Push-Location -LiteralPath $releaseRoot
try {
    & node scripts/package.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Module build failed' }
    New-Item -ItemType Directory -Path $sourceStage | Out-Null
    foreach ($name in $sourceFiles) {
        $destination = Join-Path $sourceStage $name
        $parentDir = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parentDir)) { New-Item -ItemType Directory -Path $parentDir | Out-Null }
        Copy-Item -LiteralPath (Join-Path $releaseRoot $name) -Destination $destination
    }
    Compress-Archive -LiteralPath $moduleStage -DestinationPath $moduleZip -CompressionLevel Optimal
    Compress-Archive -LiteralPath $sourceStage -DestinationPath $sourceZip -CompressionLevel Optimal
    $lines = @($moduleZip, $sourceZip) | ForEach-Object {
        $hash = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
        $hash + '  ' + [IO.Path]::GetFileName($_)
    }
    # Generated build metadata; no source or runtime configuration is rewritten.
    [IO.File]::WriteAllText($checksumFile, ($lines -join "`n") + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output $moduleZip
    Write-Output $sourceZip
    Write-Output $checksumFile
} finally {
    Pop-Location
}