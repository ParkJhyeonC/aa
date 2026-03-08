@echo off
setlocal

REM 1) 가상환경 생성/활성화
python -m venv .venv
call .venv\Scripts\activate

REM 2) 의존성 설치
python -m pip install --upgrade pip
pip install -r requirements.txt

REM 3) exe 빌드
pyinstaller --onefile --name progress-alarm progress_alarm.py

echo.
echo 빌드 완료: dist\progress-alarm.exe
endlocal
