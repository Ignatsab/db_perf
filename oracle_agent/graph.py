from __future__ import annotations

from typing import Any, Dict, List

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from oracle_agent.config import OracleAgentSettings, mcp_server_config


def build_graph(tools: List[Any], settings: OracleAgentSettings):
    model = init_chat_model(settings.openai_model).bind_tools(tools)
    system_message = SystemMessage(content=settings.system_prompt())

    async def call_model(state: MessagesState) -> Dict[str, Any]:
        response = await model.ainvoke([system_message, *state["messages"]])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "call_model")
    builder.add_conditional_edges("call_model", tools_condition)
    builder.add_edge("tools", "call_model")
    return builder.compile()


async def load_oracle_tools(settings: OracleAgentSettings) -> List[Any]:
    with mcp_server_config(settings) as server:
        client = MultiServerMCPClient({"oracle-db": server})
        return await client.get_tools()


async def ask_oracle(settings: OracleAgentSettings, question: str) -> Dict[str, Any]:
    with mcp_server_config(settings) as server:
        client = MultiServerMCPClient({"oracle-db": server})
        tools = await client.get_tools()
        graph = build_graph(tools, settings)
        return await graph.ainvoke(
            {"messages": [HumanMessage(content=question)]},
            config={"recursion_limit": 25},
        )

