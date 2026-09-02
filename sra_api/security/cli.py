from __future__ import annotations
import argparse, json
from api.security.service_key_store import ServiceKeyStore

def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-service-key"); create.add_argument("--name", required=True); create.add_argument("--scope", action="append", default=[])
    listing = sub.add_parser("list-service-keys")
    revoke = sub.add_parser("revoke-service-key"); revoke.add_argument("key_id")
    args = parser.parse_args(argv); store = ServiceKeyStore()
    if args.command == "create-service-key":
        item, raw = store.create(args.name, args.scope, "local-cli"); print(json.dumps({**item, "key": raw}))
    elif args.command == "list-service-keys": print(json.dumps(store.list_keys()))
    else: print(json.dumps(store.revoke(args.key_id, "local-cli")))

if __name__ == "__main__": main()
