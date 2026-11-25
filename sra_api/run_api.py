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
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--ssl", action="store_true", help="強制啟用 https（adhoc 自簽）")
    transport.add_argument("--http", action="store_true", help="保留既有 HTTP 監聽（不改私有 listener TLS）")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    # Actual single-process public port, not an environment hint. Optional
    # handoff startup refuses to bind this port before public Uvicorn starts.
    app.state.handoff_public_listener_port = args.port
    host_ip = "0.0.0.0" if args.public else "127.0.0.1"
    use_https = not args.http and should_use_https(force_ssl=args.ssl)

    if use_https:
        hosts = ["192.168.0.228", "192.168.0.133", "localhost", "127.0.0.1"]
        certfile, keyfile, _tmpdir = make_adhoc_cert_with_openssl(hosts)

        uvicorn.run(
            app,
            host=host_ip,
            port=args.port,
            ssl_certfile=certfile,
            ssl_keyfile=keyfile,
            workers=1,
        )
    else:
        uvicorn.run(
            app,
            host=host_ip,
            port=args.port,
            workers=1,
        )


if __name__ == "__main__":
    main()
