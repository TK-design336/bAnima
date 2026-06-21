# BlipSync / bAnima addon ZIP builder (Blender: Install from Disk)
param(
    [ValidateSet("blipsync", "banima", "both")]
    [string]$Target = "both",
    [switch]$BundleDeps,
    [string]$BlenderPython = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$blipsyncDir = Join-Path $root "blipsync"
$banimaDir = Join-Path $root "banima"
$scriptsDir = Join-Path $root "scripts"
$blipsyncVersion = "0.6.23"
$banimaVersion = "0.2.50"

function Resolve-BlenderPython {
    param([string]$ExplicitPath)
    if ($ExplicitPath -and (Test-Path $ExplicitPath)) {
        return (Resolve-Path $ExplicitPath).Path
    }
    $roots = @(
        (Join-Path $env:ProgramFiles "Blender Foundation"),
        (Join-Path ${env:ProgramFiles(x86)} "Blender Foundation")
    )
    foreach ($base in $roots) {
        if (-not (Test-Path $base)) { continue }
        $found = Get-ChildItem $base -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\python\\bin\\python\.exe$' } |
            Sort-Object FullName -Descending
        if ($found) {
            return $found[0].FullName
        }
    }
    return $null
}

function Bundle-EmotionDeps {
    param([string]$PythonExe)

    if (-not $PythonExe) {
        throw "Blender python.exe not found. Pass -BlenderPython."
    }

    $vendorDir = Join-Path $blipsyncDir "vendor"
    $modelDir = Join-Path $blipsyncDir "data\audeering_model"
    if (Test-Path $vendorDir) {
        Remove-Item $vendorDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $vendorDir -Force | Out-Null

    Write-Host "Bundling onnxruntime into blipsync/vendor ..."
    Write-Host "Python: $PythonExe"

    & $PythonExe -m pip install --upgrade pip | Out-Host
    & $PythonExe -m pip install `
        --target $vendorDir `
        onnxruntime | Out-Host

    Set-Content -Path (Join-Path $vendorDir ".bundle_ok") -Value "bundled" -Encoding ASCII

    Write-Host "Downloading audeering emotion model into blipsync/data/audeering_model ..."
    if (Test-Path $modelDir) {
        Remove-Item $modelDir -Recurse -Force
    }
    & $PythonExe (Join-Path $scriptsDir "download_emotion_model.py") | Out-Host
}

function Copy-AddonTree {
    param(
        [string]$SourceDir,
        [string]$DestDir,
        [switch]$IncludeVendor
    )
    Get-ChildItem $SourceDir -Recurse -File | Where-Object {
        $rel = $_.FullName.Substring($SourceDir.Length + 1)
        -not ($rel -match '\\__pycache__\\') `
            -and ($IncludeVendor -or -not ($rel -match '^vendor\\')) `
            -and $_.Extension -ne ".pyc"
    } | ForEach-Object {
        $rel = $_.FullName.Substring($SourceDir.Length + 1)
        $dest = Join-Path $DestDir $rel
        $destParent = Split-Path $dest -Parent
        if (-not (Test-Path $destParent)) {
            New-Item -ItemType Directory -Path $destParent -Force | Out-Null
        }
        Copy-Item $_.FullName $dest -Force
    }
}

function Build-Zip {
    param(
        [string]$StagingRoot,
        [string]$ZipPath
    )
    if (Test-Path $ZipPath) {
        Remove-Item $ZipPath -Force
    }
    Compress-Archive -Path $StagingRoot -DestinationPath $ZipPath -Force
}

if (-not (Test-Path $blipsyncDir)) {
    throw "Addon folder not found: $blipsyncDir"
}

if ($BundleDeps) {
    $py = Resolve-BlenderPython -ExplicitPath $BlenderPython
    Bundle-EmotionDeps -PythonExe $py
}

if ($Target -eq "blipsync" -or $Target -eq "both") {
    $zipPath = Join-Path $root "blipsync-$blipsyncVersion.zip"
    $staging = Join-Path $env:TEMP "blipsync-package-staging"
    if (Test-Path $staging) {
        Remove-Item $staging -Recurse -Force
    }
    $dest = Join-Path $staging "blipsync"
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-AddonTree -SourceDir $blipsyncDir -DestDir $dest -IncludeVendor:$BundleDeps
    Build-Zip -StagingRoot (Join-Path $staging "blipsync") -ZipPath $zipPath
    Remove-Item $staging -Recurse -Force
    Write-Host "Created: $zipPath"
}

if ($Target -eq "banima" -or $Target -eq "both") {
    if (-not (Test-Path $banimaDir)) {
        throw "Addon folder not found: $banimaDir"
    }
    $zipPath = Join-Path $root "banima-$banimaVersion.zip"
    $staging = Join-Path $env:TEMP "banima-package-staging"
    if (Test-Path $staging) {
        Remove-Item $staging -Recurse -Force
    }
    $dest = Join-Path $staging "banima"
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Copy-AddonTree -SourceDir $banimaDir -DestDir $dest
    Copy-AddonTree -SourceDir $blipsyncDir -DestDir (Join-Path $dest "blipsync") -IncludeVendor:$BundleDeps
    Build-Zip -StagingRoot (Join-Path $staging "banima") -ZipPath $zipPath
    Remove-Item $staging -Recurse -Force
    $sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
    Write-Host ("Created: {0} ({1} MB)" -f $zipPath, $sizeMb)
}

Write-Host ""
Write-Host "Install in Blender: Edit - Preferences - Add-ons - Install from Disk"
if (-not $BundleDeps -and ($Target -eq "banima" -or $Target -eq "both")) {
    Write-Host ""
    Write-Host "For bundled onnxruntime + emotion model build:"
    Write-Host "  .\build_package.ps1 -Target banima -BundleDeps"
}
