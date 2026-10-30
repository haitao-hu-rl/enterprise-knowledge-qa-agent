"""LangGraph 驱动的企业知识问答 Agent。

实现 "模型选择动作 -> 执行工具 -> 观察结果 -> 模型调整下一步" 的 ReAct 循环。

技术取舍（详见 docs/02-solution.md）：
- 采用 LangGraph 而非手写 while 循环，是为了获得显式的状态管理、工具调用协议、
  以及 `recursion_limit` 提供的内置步数上限（对应考核"执行步数上限"要求）。
- 模型决策由 DecisionModel 抽象隔离：默认 MockDecisionModel 保证离线可跑，
  ChatModelDecision 用于接入真实 LLM。
"""
from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from src.model.decision import DecisionModel
from src.tools.knowledge_base import KnowledgeBase
from src.tools.tools import build_tools


class AgentState(TypedDict, total=False):
    """Agent 运行时的状态。"""

    question: str
    history: list[dict[str, str]]
    observations: list[dict[str, Any]]
    step: int
    action: str
    args: dict[str, Any]
    max_steps: int
    pending_clarification: str
    final_answer: str
    citations: list[dict[str, str]]
    status: str  # "answered" | "needs_clarification" | "unknown" | "max_steps" | "tool_error"


class KnowledgeQAAgent:
    def __init__(
        self,
        kb: KnowledgeBase,
        model: DecisionModel,
        *,
        max_steps: int = 8,
        fail_search: bool = False,
        fail_read: bool = False,
    ):
        self.kb = kb
        self.model = model
        self.max_steps = max_steps
        self.tools = build_tools(kb, fail_search=fail_search, fail_read=fail_read)
        self._tool_map = {t.name: t for t in self.tools}
        self.graph = self._build_graph()

    # ---------- 节点 ----------

    def _decide(self, state: AgentState) -> AgentState:
        """决策节点：调用模型选择下一个动作。"""
        decision = self.model.decide(state)
        state["action"] = decision["action"]
        state["args"] = decision.get("args", {})
        return state

    def _route(self, state: AgentState) -> Literal["execute", "clarify", "finish"]:
        action = state.get("action")
        if action == "ask":
            return "clarify"
        if action == "finish":
            return "finish"
        return "execute"

    def _execute(self, state: AgentState) -> AgentState:
        """执行节点：调用对应工具，记录观察结果。"""
        action = state["action"]
        args = state["args"]
        tool = self._tool_map.get(_tool_name(action))
        observation: dict[str, Any] = {
            "tool": action,
            "args": args,
            "step": state.get("step", 0),
        }
        try:
            if tool is None:
                result = f"未知动作 {action}"
                observation["result"] = "ERROR"
                observation["output"] = result
            else:
                result = tool.invoke(args)
                observation["result"] = self._classify_result(action, result)
                observation["output"] = result
                if action == "search":
                    observation["docs"] = self._parse_search_docs(result)
                if action == "read":
                    doc_id = args.get("doc_id", "")
                    doc = self.kb.read(doc_id)
                    if doc:
                        observation["content"] = doc["content"]
                        observation["quote"] = self._extract_quote(state["question"], doc["content"])
                        observation["meta"] = doc
        except Exception as e:  # 工具失败：记录为 ERROR，模型据此调整（停止/追问）
            observation["result"] = "ERROR"
            observation["output"] = f"工具 {action} 调用失败：{e}"

        state.setdefault("observations", []).append(observation)
        state["step"] = state.get("step", 0) + 1
        return state

    def _clarify(self, state: AgentState) -> AgentState:
        state["status"] = "needs_clarification"
        state["final_answer"] = state["args"].get("clarification", "")
        return state

    def _finish(self, state: AgentState) -> AgentState:
        # 支持决策器覆盖状态（如工具失败时标记为 tool_error）
        state["status"] = state.get("args", {}).get("status_override", "answered")
        state["final_answer"] = state["args"].get("answer", "")
        state["citations"] = state["args"].get("citations", [])
        return state

    # ---------- 构建图 ----------

    def _build_graph(self) -> CompiledStateGraph:
        g = StateGraph(AgentState)
        g.add_node("decide", self._decide)
        g.add_node("execute", self._execute)
        g.add_node("clarify", self._clarify)
        g.add_node("finish", self._finish)

        g.add_edge(START, "decide")
        g.add_conditional_edges("decide", self._route, {
            "execute": "execute",
            "clarify": "clarify",
            "finish": "finish",
        })
        g.add_edge("execute", "decide")  # 观察结果 -> 回到决策，形成循环
        g.add_edge("clarify", END)
        g.add_edge("finish", END)
        return g.compile()

    # ---------- 公共入口 ----------

    def run(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """运行 Agent，返回结构化结果。

        达到步数上限时，LangGraph 抛 GraphRecursionError，这里捕获并转为
        明确的"未完成"状态。
        """
        from langgraph.errors import GraphRecursionError

        initial: AgentState = {
            "question": question,
            "history": history or [],
            "observations": [],
            "step": 0,
            "status": "",
            "max_steps": self.max_steps,
        }
        try:
            result = self.graph.invoke(initial, {"recursion_limit": self.max_steps + 2})
        except GraphRecursionError:
            return {
                "status": "max_steps",
                "final_answer": (
                    f"已达到最大执行步数（{self.max_steps} 步），任务未完成。"
                    "请简化问题或补充更明确的上下文。"
                ),
                "citations": [],
                "observations": initial.get("observations", []),
                "question": question,
            }

        # 若图正常结束但状态仍为空（异常兜底）
        status = result.get("status") or "unknown"
        return {
            "status": status,
            "final_answer": result.get("final_answer", ""),
            "citations": result.get("citations", []),
            "observations": result.get("observations", []),
            "question": question,
        }

    # ---------- 辅助 ----------

    def _classify_result(self, action: str, result: str) -> str:
        if action == "search":
            return "EMPTY" if "检索结果为空" in result else "HITS"
        if action == "read":
            return "MISS" if "未找到文档" in result else "OK"
        return "OK"

    def _parse_search_docs(self, result: str) -> list[dict]:
        docs = []
        for line in result.splitlines():
            line = line.strip()
            if line.startswith("- ["):
                doc_id = line[3 : line.index("]")]
                title_start = line.index("] ") + 2
                title = line[title_start : line.index(" (版本日期")]
                docs.append({"doc_id": doc_id, "title": title})
        return docs

    def _extract_quote(self, question: str, content: str) -> str:
        """抽取与问题最相关的原文片段作为引用。"""
        # 简单实现：返回包含关键词的句子
        for kw in ["天", "期限", "报销", "年假", "标准"]:
            for line in content.split("\n"):
                if kw in line:
                    return line.strip()
        return content[:120]


def _tool_name(action: str) -> str:
    return {"search": "search_documents", "read": "read_document"}.get(action, action)
