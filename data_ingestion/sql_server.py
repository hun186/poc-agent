from __future__ import annotations

from typing import Any


def detect_odbc_driver(configured_driver: Any = None, *, verbose: bool = True) -> str:
    """Choose an installed SQL Server ODBC driver, preferring configured names."""
    fallback_drivers = [
        "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server", "SQL Server Native Client 11.0", "SQL Server",
    ]
    if isinstance(configured_driver, (list, tuple)):
        configured_drivers = [str(item).strip() for item in configured_driver if str(item).strip()]
    elif configured_driver is None:
        configured_drivers = []
    else:
        raw = str(configured_driver).strip()
        configured_drivers = [] if raw.lower() in {"", "auto", "detect"} else [raw]
    candidates = configured_drivers + [driver for driver in fallback_drivers if driver not in configured_drivers]
    try:
        import pyodbc
        installed = [str(driver) for driver in pyodbc.drivers()]
    except Exception as exc:
        if configured_drivers:
            if verbose:
                print(f"⚠️ 無法列出已安裝 ODBC drivers，沿用設定檔 driver：{configured_drivers[0]}；{exc}")
            return configured_drivers[0]
        raise RuntimeError(f"無法列出已安裝 ODBC drivers，且 db.driver 未指定可用 driver：{exc}") from exc
    installed_lookup = {driver.lower(): driver for driver in installed}
    for candidate in candidates:
        matched = installed_lookup.get(candidate.lower())
        if matched:
            if verbose and configured_drivers and matched.lower() != configured_drivers[0].lower():
                print(f"⚠️ 設定檔 ODBC driver '{configured_drivers[0]}' 未安裝，自動改用已安裝 driver '{matched}'")
            return matched
    configured_text = ", ".join(configured_drivers) if configured_drivers else "auto"
    installed_text = ", ".join(installed) if installed else "（未偵測到任何 ODBC driver）"
    raise RuntimeError(
        "找不到可用的 SQL Server ODBC driver；"
        f"設定值：{configured_text}；已安裝 drivers：{installed_text}。"
        "請安裝 Microsoft ODBC Driver 18/17 for SQL Server，或調整 db.driver。"
    )
