param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$source = Join-Path $PSScriptRoot "..\skills\research-tree"
$source = [System.IO.Path]::GetFullPath($source)

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw "Skill source folder not found: $source"
}

if (-not $Destination) {
    $codexHome = $env:CODEX_HOME
    if (-not $codexHome) {
        $codexHome = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex"
    }
    $Destination = Join-Path $codexHome "skills\research-tree"
}

$Destination = [System.IO.Path]::GetFullPath($Destination)
$null = New-Item -ItemType Directory -Path $Destination -Force
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $Destination -Recurse -Force
Write-Output "Installed Research Tree skill to $Destination"
