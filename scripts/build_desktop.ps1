$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $python scripts\desktop_assets.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop assets failed.' }
$assetRoot = Join-Path $projectRoot '.scratch\desktop-assets'
$originalPath = $env:PATH
try {
    # Do not collect unrelated DLLs from other applications on the host PATH.
    $env:PATH = "$projectRoot\.venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot"
    & $python -m PyInstaller --noconfirm --clean --windowed --onedir --name EmpathyCopilot --icon "$assetRoot\icon.ico" --add-data "$assetRoot;desktop-assets" --paths $projectRoot --distpath release\desktop --workpath .scratch\desktop-build --specpath .scratch --exclude-module streamlit --exclude-module pyarrow --exclude-module matplotlib --exclude-module tkinter desktop_entry.py
}
finally { $env:PATH = $originalPath }
if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed.' }
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$compilerPath = if ($compiler) { $compiler.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe' }
if (Test-Path -LiteralPath $compilerPath) { & $compilerPath (Join-Path $PSScriptRoot 'desktop_installer.iss') }
else { Write-Warning 'Inno Setup not found. Portable folder is ready; installer was not built.' }
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
