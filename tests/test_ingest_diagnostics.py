from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_ingestion.excel_to_sql.ingest import enable_native_crash_tracebacks


class FakeFaulthandler:
    def __init__(self, enabled=False, raises=False):
        self.enabled = enabled
        self.raises = raises
        self.enable_calls = []

    def is_enabled(self):
        return self.enabled

    def enable(self, **kwargs):
        if self.raises:
            raise RuntimeError("stderr unavailable")
        self.enable_calls.append(kwargs)
        self.enabled = True


def test_enable_native_crash_tracebacks_enables_faulthandler(monkeypatch):
    fake = FakeFaulthandler(enabled=False)
    monkeypatch.setitem(sys.modules, "faulthandler", fake)

    enable_native_crash_tracebacks()

    assert fake.enable_calls == [{"file": sys.stderr, "all_threads": True}]


def test_enable_native_crash_tracebacks_ignores_diagnostic_failures(monkeypatch):
    fake = FakeFaulthandler(enabled=False, raises=True)
    monkeypatch.setitem(sys.modules, "faulthandler", fake)

    enable_native_crash_tracebacks()

    assert fake.enable_calls == []
