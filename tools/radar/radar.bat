@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "VENV=%LOCALAPPDATA%\krsc-radar-venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo [종베 레이더] 처음 실행: 전용 파이썬 환경을 만듭니다. 1~2분 걸립니다...
  py -3.12 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
  "%VENV%\Scripts\python.exe" -m pip install -q --upgrade pip
  "%VENV%\Scripts\python.exe" -m pip install -q -r "%~dp0requirements.txt"
)
"%VENV%\Scripts\python.exe" "%~dp0radar.py" %*
if /i "%~1"=="setup-kiwoom" pause
if /i "%~1"=="setup-naver" pause
if /i "%~1"=="check" pause
endlocal
