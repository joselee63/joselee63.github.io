@echo off
rem 리포트 요약 — 이 PC 도우미 (페이지의 '지금 업데이트' 버튼을 받음). 창을 닫으면 멈춤.
rem 레이더 가상환경(텔레그램 라이브러리 설치됨)을 씀. 없으면 tools\radar\radar.bat 를 먼저 한 번 실행.
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=%LOCALAPPDATA%\krsc-radar-venv\Scripts\python.exe
if not exist "%PY%" (
  echo 레이더 가상환경이 없습니다. tools\radar\radar.bat 를 먼저 실행하세요.
  pause
  exit /b 1
)
if /i "%1"=="update" (
  "%PY%" "%~dp0run.py" update
  pause
  exit /b
)
"%PY%" "%~dp0serve.py" --open
