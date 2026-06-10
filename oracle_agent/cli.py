from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from oracle_agent.config import DEFAULT_ENV_FILE, OracleAgentSettings
from oracle_agent.graph import ask_oracle, load_oracle_tools


def message_to_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Ask questions about an Oracle database through Oracle MCP and LangGraph."
    )
    parser.add_argument("question", nargs="*", help="Question to ask the Oracle agent")
    parser.add_argument("--env-file", default=DEFAULT_ENV_FILE, help="Path to env file")
    parser.add_argument("--list-tools", action="store_true", help="List MCP tools and exit")
    args = parser.parse_args()

    try:
        settings = OracleAgentSettings.from_env(args.env_file)
        if args.list_tools:
            tools = await load_oracle_tools(settings)
            for tool in tools:
                description = getattr(tool, "description", "") or ""
                print(f"- {tool.name}: {description}")
            return 0

        question = " ".join(args.question).strip()
        if not question:
            target = settings.target_relation or "the Oracle database"
            question = f"Inspect {target}, show its schema, and summarize a small data sample."

        result = await ask_oracle(settings, question)
        final_message = result["messages"][-1]
        print(message_to_text(final_message))
        return 0
    except Exception as exc:  # noqa: BLE001 - command-line diagnostic.
        print(f"Agent failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())

