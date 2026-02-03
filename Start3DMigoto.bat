@echo off
setlocal

cd /d "%~dp0"

REM ---- 3DMigoto must be installed here (same folder as Endfield.exe) ----
REM Required: d3dx.ini + dxgi.dll (or d3d11.dll depending on your setup)
REM Recommended folders: ShaderFixes, Mods

if not exist "d3dx.ini" (
  echo [ERROR] d3dx.ini not found in: %cd%
  echo Put your 3DMigoto files next to Endfield.exe
  pause
  exit /b 1
)

if not exist "dxgi.dll" (
  echo [WARN] dxgi.dll not found next to Endfield.exe
  echo If your 3DMigoto uses d3d11.dll instead, ignore this.
)

echo [OK] Starting Endfield with 3DMigoto present...
start "" "Endfield.exe"
exit /b 0
