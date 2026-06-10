# Oracle MCP LangGraph Agent

This project checks Oracle connectivity and provides a small LangGraph agent that talks to Oracle Database through Oracle's MCP toolkit.

## What It Uses

- Oracle DB credentials from `.env`
- OpenAI for the chat model
- LangGraph for the agent loop
- `langchain-mcp-adapters` to load Oracle MCP tools
- Oracle's `oracle-db-mcp-java-toolkit` MCP server from [`oracle/mcp`](https://github.com/oracle/mcp)

The agent is read-only by default: it enables `read-query`, `db-ping`, `explain-plan`, and `list-tools`.

## Setup

Use Python 3.10 or newer. Current LangChain and LangGraph releases do not install on Python 3.8.

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
```

Install Python dependencies:

```bash
python -m pip install -r requirements.txt
```

Build the Oracle MCP toolkit JAR on the machine that can reach your database:

```bash
git clone https://github.com/oracle/mcp.git
cd mcp/src/oracle-db-mcp-java-toolkit
mvn clean package
```

Set the JAR path in `.env`:

```bash
ORACLE_MCP_TOOLKIT_JAR=/absolute/path/to/oracle-db-mcp-toolkit-1.0.0.jar
```

You also need JDK 17+ and Maven 3.9+ for the Oracle MCP toolkit build.

## Environment

Use `.env.example` as the template:

```bash
cp .env.example .env
```

Required values:

```bash
HOST=...
PORT=1521
SERVICE_NAME=...
USERNAME=...
PASSWORD=...
OPENAI_API_KEY=...
ORACLE_MCP_TOOLKIT_JAR=/absolute/path/to/oracle-db-mcp-toolkit-1.0.0.jar
```

Optional table focus:

```bash
TARGET_SCHEMA=
TARGET_TABLE=YOUR_TABLE
MAX_ROWS=50
```

## Run

List the MCP tools visible to the agent:

```bash
python -m oracle_agent.cli --list-tools
```

Ask a question:

```bash
python -m oracle_agent.cli "Describe the target table and show 10 representative rows"
```

If you set `TARGET_TABLE`, you can run without a question:

```bash
python -m oracle_agent.cli
```

## HTTP MCP Mode

If you run the Oracle MCP toolkit separately over HTTP, set:

```bash
ORACLE_MCP_SERVER_URL=http://localhost:45450/mcp
ORACLE_MCP_AUTH_TOKEN=
```

When `ORACLE_MCP_SERVER_URL` is set, the agent connects over HTTP instead of spawning the Java JAR.

## Safety Note

The default `ORACLE_MCP_TOOLS` excludes write tools. If you add `write-query` or `table`, the model can access tools capable of changing schema or data. Keep database permissions least-privilege and prefer a read-only database user for agent workflows.
