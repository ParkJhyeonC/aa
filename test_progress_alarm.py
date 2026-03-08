from progress_alarm import (
    ProgressDetection,
    extract_percentage,
    extract_progress,
    extract_time_progress,
)


class DummyImage:
    pass


def test_extract_percentage_none():
    assert extract_percentage("no percent here") is None


def test_extract_percentage_max_value():
    text = "download 12% upload 99% other 5%"
    assert extract_percentage(text) == 99


def test_extract_time_progress():
    assert extract_time_progress("00:30/01:00") == 50


def test_extract_time_progress_with_hour():
    assert extract_time_progress("01:00:00 / 02:00:00") == 50


def test_extract_progress_prefers_max(monkeypatch):
    monkeypatch.setattr("progress_alarm.estimate_bar_progress", lambda _img: 40)

    result = extract_progress("75% and 00:10/00:20", DummyImage())
    assert isinstance(result, ProgressDetection)
    assert result.value == 75
    assert result.source == "percent"
