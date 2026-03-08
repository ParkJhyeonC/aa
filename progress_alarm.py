import argparse
import ctypes
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional


PERCENT_REGEX = re.compile(r"(?<!\d)(\d{1,3})\s*%")
TIME_PROGRESS_REGEX = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?)\s*/\s*(\d{1,2}:\d{2}(?::\d{2})?)"
)


@dataclass
class ProgressState:
    last_value: Optional[int] = None
    notified: bool = False
    last_alarm_at: float = 0.0


@dataclass
class ProgressDetection:
    value: int
    source: str


def _running_as_frozen_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


def _pause_before_exit_if_needed() -> None:
    if platform.system() == "Windows" and _running_as_frozen_exe():
        input("\n엔터를 누르면 종료됩니다...")


def _run_command(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)

    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    output = (result.stderr or result.stdout or "").strip()
    return False, output


def _install_python_package(package: str) -> tuple[bool, str]:
    installers = [
        [sys.executable, "-m", "pip", "install", package],
        ["py", "-m", "pip", "install", package],
    ]
    for command in installers:
        ok, message = _run_command(command)
        if ok:
            return True, f"{package} 설치 성공"
    return False, f"{package} 설치 실패"


def _ensure_tesseract_binary(auto_install_ocr: bool) -> tuple[bool, Optional[str]]:
    if platform.system() != "Windows":
        return False, "Windows 환경이 아니어서 Tesseract 자동 설치를 건너뜁니다."

    ok, _ = _run_command(["where", "tesseract"])
    if ok:
        return True, None

    if not auto_install_ocr:
        return False, "Tesseract 실행 파일이 없습니다."

    winget_ok, _ = _run_command(["winget", "--version"])
    if not winget_ok:
        return False, "winget을 찾지 못해 Tesseract 자동 설치를 할 수 없습니다."

    ok, message = _run_command(
        ["winget", "install", "--id", "UB-Mannheim.TesseractOCR", "-e", "--silent"]
    )
    if not ok:
        return False, f"winget으로 Tesseract 자동 설치 실패: {message}"

    ok, _ = _run_command(["where", "tesseract"])
    if ok:
        return True, "winget으로 Tesseract를 자동 설치했습니다."
    return False, "자동 설치 후에도 Tesseract 경로를 찾지 못했습니다."


def _parse_time_to_seconds(value: str) -> Optional[int]:
    parts = value.split(":")
    if len(parts) == 2:
        mm, ss = parts
        if not (mm.isdigit() and ss.isdigit()):
            return None
        return int(mm) * 60 + int(ss)

    if len(parts) == 3:
        hh, mm, ss = parts
        if not (hh.isdigit() and mm.isdigit() and ss.isdigit()):
            return None
        return int(hh) * 3600 + int(mm) * 60 + int(ss)

    return None


def extract_percentage(text: str) -> Optional[int]:
    candidates = []
    for match in PERCENT_REGEX.finditer(text):
        value = int(match.group(1))
        if 0 <= value <= 100:
            candidates.append(value)
    if not candidates:
        return None
    return max(candidates)


def extract_time_progress(text: str) -> Optional[int]:
    candidates = []
    for match in TIME_PROGRESS_REGEX.finditer(text):
        current_raw, total_raw = match.group(1), match.group(2)
        current_seconds = _parse_time_to_seconds(current_raw)
        total_seconds = _parse_time_to_seconds(total_raw)

        if current_seconds is None or total_seconds is None:
            continue
        if total_seconds <= 0:
            continue

        ratio = max(0.0, min(1.0, current_seconds / total_seconds))
        candidates.append(int(round(ratio * 100)))

    if not candidates:
        return None
    return max(candidates)


def estimate_bar_progress(image) -> Optional[int]:
    import numpy as np

    rgb = np.array(image.convert("RGB"), dtype=np.int16)
    h, w, _ = rgb.shape
    if w < 80 or h < 20:
        return None

    min_width = int(w * 0.25)
    max_width = int(w * 0.95)
    best: Optional[tuple[float, int]] = None

    y_step = max(2, h // 120)
    for y in range(0, h, y_step):
        row = rgb[y]
        diffs = np.linalg.norm(row[1:] - row[:-1], axis=1)
        strong_edges = np.where(diffs > 45)[0]
        if strong_edges.size < 3:
            continue

        left = int(strong_edges[0])
        right = int(strong_edges[-1])
        span = right - left
        if span < min_width or span > max_width:
            continue

        inner = diffs[left:right]
        if inner.size < 8:
            continue

        transition = int(np.argmax(inner)) + left
        left_len = transition - left
        right_len = right - transition
        if left_len < int(span * 0.08) or right_len < int(span * 0.08):
            continue

        left_mean = row[left:transition].mean(axis=0)
        right_mean = row[transition:right].mean(axis=0)
        color_gap = float(np.linalg.norm(left_mean - right_mean))
        if color_gap < 20:
            continue

        left_std = row[left:transition].std()
        right_std = row[transition:right].std()
        stability = 1.0 / (1.0 + left_std + right_std)
        score = color_gap * stability * span

        ratio = (transition - left) / span
        progress = int(round(max(0.0, min(1.0, ratio)) * 100))

        if best is None or score > best[0]:
            best = (score, progress)

    if best is None:
        return None
    return best[1]


def extract_progress(text: str, screen_image) -> Optional[ProgressDetection]:
    candidates: list[ProgressDetection] = []
    percent = extract_percentage(text)
    time_progress = extract_time_progress(text)
    bar_progress = estimate_bar_progress(screen_image)

    if percent is not None:
        candidates.append(ProgressDetection(value=percent, source="percent"))
    if time_progress is not None:
        candidates.append(ProgressDetection(value=time_progress, source="time"))
    if bar_progress is not None:
        candidates.append(ProgressDetection(value=bar_progress, source="bar"))

    if not candidates:
        return None

    return max(candidates, key=lambda item: item.value)


def capture_screen_image():
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitor = sct.monitors[0]
        shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def _build_tesseract_reader(
    tesseract_cmd: Optional[str],
    auto_install_ocr: bool,
) -> tuple[Optional[Callable[[object], str]], Optional[str]]:
    try:
        import pytesseract
    except Exception:
        if auto_install_ocr:
            ok, _ = _install_python_package("pytesseract")
            if ok:
                import pytesseract
            else:
                return None, "pytesseract 자동 설치에 실패했습니다."
        else:
            return None, "pytesseract 패키지가 없어 Tesseract OCR을 사용할 수 없습니다."

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    else:
        _, warn = _ensure_tesseract_binary(auto_install_ocr)
        if warn and auto_install_ocr:
            print(f"[WARN] {warn}")

    def _reader(image) -> str:
        grayscale = image.convert("L")
        return pytesseract.image_to_string(grayscale, lang="eng")

    try:
        _ = pytesseract.get_tesseract_version()
    except Exception:
        return None, (
            "Tesseract 실행 파일을 찾지 못해 OCR(텍스트/시간) 감지를 비활성화합니다. "
            "--tesseract-cmd 옵션으로 경로를 지정할 수 있습니다."
        )

    return _reader, None


def _build_easyocr_reader(
    auto_install_ocr: bool,
) -> tuple[Optional[Callable[[object], str]], Optional[str]]:
    try:
        import easyocr
        import numpy as np
    except Exception:
        if not auto_install_ocr:
            return None, "easyocr 패키지가 없어 EasyOCR을 사용할 수 없습니다."

        ok, _ = _install_python_package("easyocr")
        if not ok:
            return None, "easyocr 자동 설치에 실패했습니다."

        try:
            import easyocr
            import numpy as np
        except Exception:
            return None, "easyocr 설치 후 import에 실패했습니다."

    try:
        reader = easyocr.Reader(["en"], gpu=False)
    except Exception as exc:
        return None, f"EasyOCR 초기화에 실패했습니다: {exc}"

    def _reader(image) -> str:
        img = np.array(image.convert("RGB"))
        results = reader.readtext(img, detail=0, paragraph=True)
        return "\n".join(results)

    return _reader, None


def _build_ocr_reader(
    ocr_engine: str,
    tesseract_cmd: Optional[str],
    auto_install_ocr: bool,
) -> tuple[Optional[Callable[[object], str]], Optional[str]]:
    if ocr_engine == "none":
        return None, "OCR을 비활성화했습니다(바 기반 감지만 사용)."

    if ocr_engine == "tesseract":
        return _build_tesseract_reader(tesseract_cmd, auto_install_ocr)

    if ocr_engine == "easyocr":
        return _build_easyocr_reader(auto_install_ocr)

    reader, warning = _build_tesseract_reader(tesseract_cmd, auto_install_ocr)
    if reader is not None:
        return reader, None

    easy_reader, easy_warning = _build_easyocr_reader(auto_install_ocr)
    if easy_reader is not None:
        return easy_reader, (
            "Tesseract를 사용할 수 없어 EasyOCR로 대체했습니다. "
            f"(참고: {warning})"
        )

    return None, (
        "OCR 엔진을 사용할 수 없어 바(progress bar) 기반 감지만 사용합니다. "
        f"(Tesseract: {warning} / EasyOCR: {easy_warning})"
    )


def send_alarm(progress: int) -> None:
    title = "진행률 알림"
    message = f"진행률이 {progress}%에 도달했습니다."
    print(f"[ALARM] {message}")

    if platform.system() == "Windows":
        MB_OK = 0x0
        ctypes.windll.user32.MessageBoxW(0, message, title, MB_OK)
        import winsound

        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS)


def monitor_progress(
    threshold: int,
    interval: float,
    reset_gap: int,
    alarm_repeat_seconds: float,
    ocr_engine: str,
    auto_install_ocr: bool,
    tesseract_cmd: Optional[str] = None,
) -> None:
    ocr_reader, ocr_warning = _build_ocr_reader(ocr_engine, tesseract_cmd, auto_install_ocr)
    if ocr_warning:
        print(f"[WARN] {ocr_warning}")
    if ocr_reader is None:
        print("[WARN] 텍스트/시간 인식 없이 바(progress bar) 기반 감지만 동작합니다.")

    state = ProgressState()
    print(
        "진행률 모니터링 시작: "
        f"threshold={threshold}%, interval={interval}s, reset_gap={reset_gap}%, "
        f"alarm_repeat_seconds={alarm_repeat_seconds}s, ocr_engine={ocr_engine}, "
        f"auto_install_ocr={auto_install_ocr}"
    )
    print("종료하려면 Ctrl+C를 누르세요.")

    try:
        while True:
            try:
                image = capture_screen_image()
                text = ocr_reader(image) if ocr_reader else ""
                detection = extract_progress(text, image)

                if detection is None:
                    print("[INFO] 진행률(퍼센트/시간/바)을 찾지 못했습니다.")
                    time.sleep(interval)
                    continue

                progress = detection.value
                source = detection.source
                state.last_value = progress
                print(f"[INFO] 현재 진행률: {progress}% (source={source})")

                now = time.time()
                should_notify = False

                if progress >= threshold and not state.notified:
                    should_notify = True
                elif progress >= threshold and alarm_repeat_seconds > 0:
                    if now - state.last_alarm_at >= alarm_repeat_seconds:
                        should_notify = True

                if should_notify:
                    send_alarm(progress)
                    state.notified = True
                    state.last_alarm_at = now

                if progress <= max(0, threshold - reset_gap):
                    state.notified = False

                time.sleep(interval)
            except Exception as exc:
                print(f"[ERROR] 진행률 감지 중 오류가 발생했습니다: {exc}")
                time.sleep(max(interval, 2.0))
    except KeyboardInterrupt:
        print("\n사용자 요청으로 모니터링을 종료했습니다.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="화면 내 진행률(퍼센트/시간/바)을 계속 감지하고 99% 이상일 때 알림을 보냅니다."
    )
    parser.add_argument("--threshold", type=int, default=99, help="알림 임계값(기본: 99)")
    parser.add_argument("--interval", type=float, default=1.0, help="감시 주기 초(기본: 1.0)")
    parser.add_argument(
        "--reset-gap",
        type=int,
        default=5,
        help="진행률이 threshold-reset_gap 이하로 내려갔을 때 재알림 허용(기본: 5)",
    )
    parser.add_argument(
        "--alarm-repeat-seconds",
        type=float,
        default=0.0,
        help="임계치 이상 구간에서 알림 반복 간격(초). 0이면 최초 1회만 알림",
    )
    parser.add_argument(
        "--ocr-engine",
        type=str,
        choices=["auto", "tesseract", "easyocr", "none"],
        default="auto",
        help="OCR 엔진 선택(auto/tesseract/easyocr/none, 기본: auto)",
    )
    parser.add_argument(
        "--auto-install-ocr",
        action="store_true",
        help="OCR 엔진/의존성이 없으면 자동 설치를 시도합니다.",
    )
    parser.add_argument(
        "--tesseract-cmd",
        type=str,
        default=None,
        help="tesseract 실행 파일 경로(예: C:\\Program Files\\Tesseract-OCR\\tesseract.exe)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not (0 <= args.threshold <= 100):
        raise ValueError("threshold는 0~100 사이여야 합니다.")
    if args.interval <= 0:
        raise ValueError("interval은 0보다 커야 합니다.")
    if args.alarm_repeat_seconds < 0:
        raise ValueError("alarm-repeat-seconds는 0 이상이어야 합니다.")

    monitor_progress(
        threshold=args.threshold,
        interval=args.interval,
        reset_gap=args.reset_gap,
        alarm_repeat_seconds=args.alarm_repeat_seconds,
        ocr_engine=args.ocr_engine,
        auto_install_ocr=args.auto_install_ocr,
        tesseract_cmd=args.tesseract_cmd,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FATAL] 프로그램이 종료되었습니다: {exc}")
        _pause_before_exit_if_needed()
        raise
