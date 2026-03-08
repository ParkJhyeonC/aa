# Progress Alarm (99% 알림)

화면 전체를 분석해서 진행률을 추정하고, 진행률이 **99% 이상**이 되면 알림을 보내는 프로그램입니다.

## 지원하는 진행률 형식
- 퍼센트 텍스트: `87%`
- 시간형 텍스트: `00:30/01:00`, `01:00:00/02:00:00`
- 가로 바 형태 프로그레스(채워진 영역/빈 영역 색상 차이 기반 추정)

여러 형식이 동시에 감지되면 가장 큰 진행률 값을 사용합니다.

## 종료할 때까지 계속 모니터링
- 프로그램은 사용자가 종료(`Ctrl+C`)할 때까지 계속 화면을 확인합니다.
- 매 감시 주기마다 현재 감지된 진행률을 콘솔에 안내합니다.
- 임계치 도달 알림은 기본적으로 1회만 보내며, 필요하면 반복 알림도 설정할 수 있습니다.

## 동작 방식
1. 주기적으로 화면 전체 캡처
2. OCR(Tesseract)로 텍스트 추출
3. 퍼센트/시간형 진행률 파싱
4. 이미지에서 가로 진행 바 비율 추정
5. 현재 진행률을 매 주기 콘솔에 출력
6. 기본값 99% 이상이면 알림 표시

## 준비 사항 (Windows 기준)
1. Python 3.10+ 설치
2. Tesseract OCR 설치
   - 기본 경로 예시: `C:\Program Files\Tesseract-OCR\tesseract.exe`

## 실행 (파이썬)
```bash
pip install -r requirements.txt
python progress_alarm.py --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

옵션:
- `--threshold` : 알림 임계값 (기본 99)
- `--interval` : 감시 간격 초 (기본 1.0)
- `--reset-gap` : 진행률이 충분히 내려가면 재알림 허용 (기본 5)
- `--alarm-repeat-seconds` : 임계치 이상일 때 반복 알림 간격(초, 기본 0=최초 1회)

예시(30초마다 반복 알림):
```bash
python progress_alarm.py --alarm-repeat-seconds 30 --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## exe 빌드
```bat
build_exe.bat
```

빌드 결과물:
- `dist\progress-alarm.exe`

## 주의 사항
- OCR 기반이라 화면 글꼴, 해상도, 배경 대비에 따라 인식률이 달라질 수 있습니다.
- 바 형태 감지는 화면 내 요소(테마/그라데이션/애니메이션)에 따라 오인식이 발생할 수 있습니다.
