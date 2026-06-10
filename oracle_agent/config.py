from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from check_oracle_connection import env_value, load_env_file


DEFAULT_ENV_FILE = ".env"
DEFAULT_MODEL = "openai:gpt-4.1-mini"
DEFAULT_MCP_TOOLS = "read-query,db-ping,explain-plan,list-tools"
DEFAULT_MAX_ROWS = 50


@dataclass(frozen=True)
class OracleAgentSettings:
    host: str
    port: int
    service_name: str
    username: str
    password: str
    openai_model: str
    target_table: Optional[str]
    target_schema: Optional[str]
    max_rows: int
    mcp_tools: str
    mcp_toolkit_jar: Optional[str]
    mcp_server_url: Optional[str]
    mcp_auth_token: Optional[str]
    java_bin: str
    mcp_config_file: Optional[str]

    @property
    def jdbc_url(self) -> str:
        return f"jdbc:oracle:thin:@{self.host}:{self.port}/{self.service_name}"

    @property
    def target_relation(self) -> Optional[str]:
        if not self.target_table:
            return None
        if self.target_schema:
            return f"{self.target_schema}.{self.target_table}"
        return self.target_table

    @classmethod
    def from_env(cls, env_file: str = DEFAULT_ENV_FILE) -> "OracleAgentSettings":
        load_env_file(Path(env_file))

        port_raw = env_value("PORT", "ORACLE_PORT")
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError(f"PORT must be an integer, got {port_raw!r}") from exc

        max_rows_raw = os.getenv("MAX_ROWS", str(DEFAULT_MAX_ROWS))
        try:
            max_rows = int(max_rows_raw)
        except ValueError as exc:
            raise ValueError(f"MAX_ROWS must be an integer, got {max_rows_raw!r}") from exc
        if max_rows < 1:
            raise ValueError("MAX_ROWS must be at least 1")

        if not os.getenv("OPENAI_API_KEY"):
            raise ValueError("Missing required environment variable: OPENAI_API_KEY")

        return cls(
            host=env_value("HOST", "ORACLE_HOST"),
            port=port,
            service_name=env_value("SERVICE_NAME", "ORACLE_SERVICE_NAME"),
            username=env_value("USERNAME", "ORACLE_USERNAME", "ORACLE_USER"),
            password=env_value("PASSWORD", "ORACLE_PASSWORD"),
            openai_model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            target_table=os.getenv("TARGET_TABLE") or None,
            target_schema=os.getenv("TARGET_SCHEMA") or None,
            max_rows=max_rows,
            mcp_tools=os.getenv("ORACLE_MCP_TOOLS", DEFAULT_MCP_TOOLS),
            mcp_toolkit_jar=os.getenv("ORACLE_MCP_TOOLKIT_JAR") or None,
            mcp_server_url=os.getenv("ORACLE_MCP_SERVER_URL") or None,
            mcp_auth_token=os.getenv("ORACLE_MCP_AUTH_TOKEN") or None,
            java_bin=os.getenv("JAVA_BIN", "java"),
            mcp_config_file=os.getenv("ORACLE_MCP_CONFIG_FILE") or None,
        )

    def system_prompt(self) -> str:
        target = self.target_relation or "not fixed; discover relevant tables first"
        return (
            "You are an Oracle database analysis agent. Use the Oracle MCP tools to "
            "answer questions with live database evidence.\n\n"
            "Safety rules:\n"
            "- Use read-only SQL only. Prefer the read-query tool.\n"
            "- Do not call tools that modify schema or data.\n"
            "- Do not reveal credentials, connection strings, or secrets.\n"
            f"- Limit exploratory result sets to {self.max_rows} rows or fewer.\n"
            "- Inspect schema before writing non-trivial queries.\n"
            "- Include the SQL you used when it helps the user trust the answer.\n\n"
            f"Target table: {target}."
        )


def yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def render_runtime_mcp_config(settings: OracleAgentSettings) -> str:
    return "\n".join(
        [
            "dataSources:",
            "  default:",
            f"    url: {yaml_quote(settings.jdbc_url)}",
            f"    user: {yaml_quote(settings.username)}",
            f"    password: {yaml_quote(settings.password)}",
            "",
        ]
    )


@contextmanager
def mcp_server_config(settings: OracleAgentSettings) -> Iterator[Dict[str, Any]]:
    if settings.mcp_server_url:
        server: Dict[str, Any] = {
            "transport": "http",
            "url": settings.mcp_server_url,
        }
        if settings.mcp_auth_token:
            server["headers"] = {"Authorization": f"Bearer {settings.mcp_auth_token}"}
        yield server
        return

    if not settings.mcp_toolkit_jar:
        raise ValueError(
            "Set ORACLE_MCP_TOOLKIT_JAR to the built oracle-db-mcp-toolkit jar, "
            "or set ORACLE_MCP_SERVER_URL for an already-running HTTP MCP server."
        )

    config_path = settings.mcp_config_file
    temp_path: Optional[str] = None
    if not config_path:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="oracle-mcp-",
            suffix=".yaml",
            delete=False,
        ) as temp_file:
            temp_file.write(render_runtime_mcp_config(settings))
            temp_path = temp_file.name
        os.chmod(temp_path, 0o600)
        config_path = temp_path

    args = [
        f"-DconfigFile={config_path}",
        f"-Dtools={settings.mcp_tools}",
        "-jar",
        settings.mcp_toolkit_jar,
    ]

    try:
        yield {
            "transport": "stdio",
            "command": settings.java_bin,
            "args": args,
        }
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass

