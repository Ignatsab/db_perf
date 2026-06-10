#!/usr/bin/env python3
"""Check network and login connectivity to an Oracle database."""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
from pathlib import Path


DEFAULT_ENV_FILE = ".env"
DEFAULT_TIMEOUT_SECONDS = 5.0


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE pairs without overriding existing env vars."""
    if not path.exists():
        return

    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ValueError(f"{path}:{line_number}: invalid env var name {key!r}")

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)


def env_value(*names: str, required: bool = True) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    if required:
        joined = " or ".join(names)
        raise ValueError(f"Missing required environment variable: {joined}")
    return None


def mask(value: str | None) -> str:
    if not value:
        return "<empty>"
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[:1]}{'*' * (len(value) - 2)}{value[-1:]}"


def resolve_host(host: str, port: int) -> list[str]:
    try:
        addrinfo = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(
            f"DNS lookup failed for HOST={host!r}: {exc}. "
            "Check the hostname, VPN, private DNS, or /etc/hosts setup."
        ) from exc

    addresses = sorted({item[4][0] for item in addrinfo})
    return addresses


def check_tcp(host: str, port: int, timeout: float) -> None:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except socket.timeout as exc:
        raise RuntimeError(
            f"TCP connection to {host}:{port} timed out after {timeout:g}s. "
            "This usually means firewall, VPN, routing, security group, or allowlist trouble."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"TCP connection to {host}:{port} failed: {exc}. "
            "If DNS resolved, check the port, listener, network route, VPN, and firewall rules."
        ) from exc


def explain_oracle_error(message: str) -> str:
    hints = {
        "ORA-01017": "Invalid username/password, or the user is not allowed to log in that way.",
        "ORA-12154": "Oracle could not resolve the connect identifier. Recheck SERVICE_NAME/DSN.",
        "ORA-12170": "Oracle connection timed out. Check firewall, VPN, route, or listener reachability.",
        "ORA-12505": "Listener exists, but does not know the SID. Use SERVICE_NAME, not SID, unless your DBA says otherwise.",
        "ORA-12514": "Listener exists, but does not know this SERVICE_NAME. Recheck SERVICE_NAME with your DBA.",
        "ORA-12541": "No Oracle listener answered on that host/port.",
        "ORA-12543": "Destination host is unreachable from this machine.",
        "ORA-12545": "Target host does not exist or cannot be reached.",
        "ORA-28000": "The Oracle account is locked.",
        "DPY-6005": "python-oracledb could not connect. The nested error usually has the exact network/listener cause.",
    }
    for code, hint in hints.items():
        if code in message:
            return hint
    return "Read the Oracle error above; it usually identifies whether this is credentials, service name, listener, or network."


def check_oracle_login(
    host: str,
    port: int,
    service_name: str,
    username: str,
    password: str,
) -> None:
    try:
        import oracledb
    except ImportError as exc:
        raise RuntimeError(
            "Missing Python package 'oracledb'. Install it with: python -m pip install -r requirements.txt"
        ) from exc

    client_lib_dir = env_value("ORACLE_CLIENT_LIB_DIR", "ORACLE_LIB_DIR", required=False)
    if client_lib_dir:
        try:
            oracledb.init_oracle_client(lib_dir=client_lib_dir)
        except Exception as exc:  # noqa: BLE001 - show exact driver message.
            raise RuntimeError(f"Failed to initialize Oracle Client from {client_lib_dir}: {exc}") from exc

    dsn = oracledb.makedsn(host, port, service_name=service_name)
    try:
        with oracledb.connect(user=username, password=password, dsn=dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("select 1 from dual")
                result = cursor.fetchone()
            print("Oracle login: OK")
            print(f"Database version: {connection.version}")
            print(f"Test query result: {result[0] if result else '<no row>'}")
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic script.
        message = str(exc)
        raise RuntimeError(f"Oracle login failed: {message}\nHint: {explain_oracle_error(message)}") from exc


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether this machine can reach and log in to an Oracle database."
    )
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Path to .env file")
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="TCP timeout in seconds",
    )
    args = parser.parse_args()

    try:
        load_env_file(Path(args.env_file))

        host = env_value("HOST", "ORACLE_HOST")
        port_raw = env_value("PORT", "ORACLE_PORT")
        service_name = env_value("SERVICE_NAME", "ORACLE_SERVICE_NAME")
        username = env_value("USERNAME", "ORACLE_USERNAME", "ORACLE_USER")
        password = env_value("PASSWORD", "ORACLE_PASSWORD")

        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError(f"PORT must be an integer, got {port_raw!r}") from exc

        print("Loaded configuration:")
        print(f"  HOST={host}")
        print(f"  PORT={port}")
        print(f"  SERVICE_NAME={service_name}")
        print(f"  USERNAME={username}")
        print(f"  PASSWORD={mask(password)}")

        addresses = resolve_host(host, port)
        print(f"DNS lookup: OK ({', '.join(addresses)})")

        check_tcp(host, port, args.timeout)
        print(f"TCP connection: OK ({host}:{port})")

        check_oracle_login(host, port, service_name, username, password)
        print("Overall result: SUCCESS")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level diagnostic output.
        print(f"Overall result: FAILED\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
