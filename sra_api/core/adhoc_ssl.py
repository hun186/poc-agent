# api/core/adhoc_ssl.py
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple


class AdhocSSLError(RuntimeError):
    pass


def is_windows() -> bool:
    return "windows" in platform.system().lower()


def should_use_https(*, force_ssl: bool) -> bool:
    """
    仿你 Dash 的概念：
    - 非 Windows：預設 https（adhoc）
    - Windows：預設 http，除非 force_ssl=True
    """
    return (not is_windows()) or force_ssl


def make_adhoc_cert_with_openssl(
    hosts: List[str],
    *,
    days: int = 30,
    openssl_cmd: str = "openssl",
    tmpdir: Optional[str] = None,
) -> Tuple[str, str, str]:
    """
    產生 adhoc 自簽憑證（含 SAN：IP/DNS）
    回傳：(cert_path, key_path, tmpdir)
    - tmpdir 供你需要時清理或 debug
    """
    if not hosts:
        raise ValueError("hosts 不可為空")

    if tmpdir is None:
        tmpdir = tempfile.mkdtemp(prefix="sra_https_adhoc_")

    tmp = Path(tmpdir)
    cert_path = tmp / "adhoc.crt"
    key_path = tmp / "adhoc.key"
    cnf_path = tmp / "openssl.cnf"

    alt_lines = []
    ip_i, dns_i = 1, 1
    for h in hosts:
        # 簡單判斷是否為 IPv4 字串
        if all(c.isdigit() or c == "." for c in h):
            alt_lines.append(f"IP.{ip_i} = {h}")
            ip_i += 1
        else:
            alt_lines.append(f"DNS.{dns_i} = {h}")
            dns_i += 1

    cnf = f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C = TW
ST = Taipei
L = Taipei
O = SRA-API
CN = {hosts[0]}

[v3_req]
subjectAltName = @alt_names

[alt_names]
{os.linesep.join(alt_lines)}
""".strip()

    cnf_path.write_text(cnf, encoding="utf-8")

    cmd = [
        openssl_cmd, "req", "-x509", "-nodes",
        "-days", str(days),
        "-newkey", "rsa:2048",
        "-keyout", str(key_path),
        "-out", str(cert_path),
        "-config", str(cnf_path),
    ]

    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise AdhocSSLError(f"找不到 openssl：'{openssl_cmd}' 不存在或不在 PATH")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", "ignore")
        raise AdhocSSLError(f"openssl 產生憑證失敗：{err}")

    return str(cert_path), str(key_path), tmpdir
