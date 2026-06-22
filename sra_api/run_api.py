# api/run_api.py
from __future__ import annotations

import argparse

import uvicorn

from api.main import app
from api.core.adhoc_ssl import should_use_https, make_adhoc_cert_with_openssl


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true", help="host=0.0.0.0")
    parser.add_argument("--port", type=int, default=9002)
    parser.add_argument("--ssl", action="store_true", help="強制啟用 https（adhoc 自簽）")
    args = parser.parse_args()

    host_ip = "0.0.0.0" if args.public else "127.0.0.1"
    use_https = should_use_https(force_ssl=args.ssl)

    if use_https:
        hosts = ["192.168.0.228", "192.168.0.133", "localhost", "127.0.0.1"]
        certfile, keyfile, _tmpdir = make_adhoc_cert_with_openssl(hosts)

        uvicorn.run(
            app,
            host=host_ip,
            port=args.port,
            ssl_certfile=certfile,
            ssl_keyfile=keyfile,
        )
    else:
        uvicorn.run(
            app,
            host=host_ip,
            port=args.port,
        )


if __name__ == "__main__":
    main()
