#!/usr/bin/env python3
"""
Простой CLI для работы с OVSDB-схемой system.ovsschema.
Пример: python3 cli.py set interface eth0 ip 10.0.0.2/24
"""
import argparse
import sys
import time
from typing import Any, Dict

try:
    import ovs.db.idl as ovs_idl
    import ovs.poller as ovs_poller
except ModuleNotFoundError:
    ovs_idl = None
    ovs_poller = None

SCHEMA = "src/schema/system.ovsschema"
REMOTE = "unix:/var/run/openvswitch/db.sock"
CONNECT_TIMEOUT = 5.0


def require_ovs():
    if ovs_idl is None or ovs_poller is None:
        raise RuntimeError("Python bindings for OVS are missing. Install python3-openvswitch.")


def get_idl(remote: str, schema_path: str):
    require_ovs()
    helper = ovs_idl.SchemaHelper(location=schema_path)
    helper.register_all()
    idl = ovs_idl.Idl(remote, helper)
    wait_for_idl(idl, remote)
    return idl


def wait_for_idl(idl, remote: str, timeout: float = CONNECT_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        poller = ovs_poller.Poller()
        idl.run()
        has_connected = getattr(idl, "has_ever_connected", None)
        if has_connected is None or has_connected():
            return
        idl.wait(poller)
        poller.timer_wait(100)
        poller.block()
    raise TimeoutError(f"Timed out connecting to OVSDB remote {remote}")


def upsert_row(idl, table: str, match: Dict[str, Any], updates: Dict[str, Any]):
    tbl = idl.tables.get(table)
    if not tbl:
        raise RuntimeError(f"Table {table} not found")
    row = None
    for r in tbl.rows.values():
        ok = True
        for k, v in match.items():
            if not hasattr(r, k) or getattr(r, k) != v:
                ok = False
                break
        if ok:
            row = r
            break
    txn = ovs_idl.Transaction(idl)
    if row is None:
        row = txn.insert(tbl)
        for k, v in match.items():
            setattr(row, k, v)
    for k, v in updates.items():
        setattr(row, k, v)
    status = txn.commit_block()
    if status not in (
        ovs_idl.Transaction.SUCCESS,
        ovs_idl.Transaction.UNCHANGED,
    ):
        raise RuntimeError(f"Transaction failed: {status}")


def handle_set(args):
    idl = get_idl(args.remote, args.schema)
    idl.run()
    if args.resource == "interface":
        updates: Dict[str, Any] = {}
        if args.key in ("ip", "state"):
            updates[args.key] = args.value
        elif args.key in ("mtu", "vlan"):
            updates[args.key] = int(args.value)
        else:
            raise RuntimeError(f"Unknown interface field {args.key}")
        upsert_row(idl, "Interface", {"name": args.name}, updates)
    elif args.resource == "system":
        updates: Dict[str, Any] = {args.key: args.value}
        upsert_row(idl, "System", {}, updates)
    elif args.resource == "vm":
        updates: Dict[str, Any] = {}
        if args.key in ("cpu", "ram"):
            updates[args.key] = int(args.value)
        elif args.key == "pci_passthrough":
            updates[args.key] = [item for item in args.value.split(",") if item]
        else:
            updates[args.key] = args.value
        upsert_row(idl, "VirtualMachine", {"name": args.name}, updates)
    elif args.resource == "storage":
        updates: Dict[str, Any] = {}
        if args.key == "lun":
            updates[args.key] = int(args.value)
        else:
            updates[args.key] = args.value
        upsert_row(idl, "Storage", {"target_iqn": args.name}, updates)
    else:
        raise RuntimeError(f"Unknown resource {args.resource}")
    print("OK")


def handle_show(args):
    idl = get_idl(args.remote, args.schema)
    idl.run()
    tbl = idl.tables.get(args.table)
    if not tbl:
        raise RuntimeError(f"Table {args.table} not found")
    for row in tbl.rows.values():
        print(row)


def build_parser():
    parser = argparse.ArgumentParser(description="OVSDB CLI wrapper")
    parser.add_argument("--remote", default=REMOTE, help="OVSDB remote (default unix socket)")
    parser.add_argument("--schema", default=SCHEMA, help="Path to ovsschema")
    sub = parser.add_subparsers(dest="cmd", required=True)

    setp = sub.add_parser("set", help="Set values")
    setp.add_argument("resource", choices=["interface", "system", "vm", "storage"])
    setp.add_argument("name", help="Resource name (ignored for system; target_iqn for storage)")
    setp.add_argument("key", help="Field name")
    setp.add_argument("value", help="Field value")
    setp.set_defaults(func=handle_set)

    showp = sub.add_parser("show", help="Show table rows")
    showp.add_argument("table", help="Table name")
    showp.set_defaults(func=handle_show)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
