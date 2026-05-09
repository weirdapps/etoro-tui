import time
from pathlib import Path

from etoro_tui.clients.signals import SignalsReader


def test_reads_known_signals(tmp_signals_csv: Path):
    r = SignalsReader(tmp_signals_csv)
    out = r.read()
    assert out["AAPL"] == "BUY"
    assert out["MSFT"] == "HOLD"
    assert out["TSLA"] == "SELL"
    assert out["TM"] is None  # 'I' inconclusive maps to None


def test_missing_file_returns_empty(tmp_path: Path):
    r = SignalsReader(tmp_path / "nope.csv")
    assert r.read() == {}


def test_mtime_cache_no_reread(tmp_signals_csv: Path, monkeypatch):
    r = SignalsReader(tmp_signals_csv)
    r.read()
    # Force a second call. Mutate file content WITHOUT updating mtime to prove cache.
    new_text = "TKR,NAME,BS\nXXX,X,B\n"
    tmp_signals_csv.write_text(new_text)
    # Reset mtime to original to simulate "no change"
    stat = (tmp_signals_csv.stat().st_atime, r._cache_mtime)
    import os

    os.utime(tmp_signals_csv, stat)
    out = r.read()
    # Cached, so XXX should NOT appear
    assert "XXX" not in out
    assert "AAPL" in out


def test_mtime_change_triggers_reread(tmp_signals_csv: Path):
    r = SignalsReader(tmp_signals_csv)
    r.read()
    time.sleep(0.01)  # ensure mtime advances
    tmp_signals_csv.write_text("TKR,NAME,BS\nXXX,X,B\n")
    out = r.read()
    assert out == {"XXX": "BUY"}
