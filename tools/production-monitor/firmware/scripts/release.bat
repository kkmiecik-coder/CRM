@echo off
setlocal
pushd "%~dp0\.."

pio run -e esp12e
if errorlevel 1 (echo build failed & exit /b 1)

gzip -f -k .pio\build\esp12e\firmware.bin

for /f "tokens=2 delims==" %%i in ('wmic os get localdatetime /value ^| find "="') do set DT=%%i
set STAMP=%DT:~0,8%

if not exist release mkdir release
copy .pio\build\esp12e\firmware.bin     release\production-monitor-%STAMP%.bin >nul
copy .pio\build\esp12e\firmware.bin.gz  release\production-monitor-%STAMP%.bin.gz >nul

echo Released: release\production-monitor-%STAMP%.bin.gz
popd
