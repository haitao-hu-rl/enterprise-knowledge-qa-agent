"""Agent 可调用工具的 LangChain 工具封装。

将 KnowledgeBase 的检索/读取能力包装为 tool，并支持故障注入（工具失败验收点）。
"""
from __future__ import annotations

from langchain_core.tools import tool

from src.tools.knowledge_base import KnowledgeBase


def build_tools(kb: KnowledgeBase, *, fail_search: bool = False, fail_read: bool = False):
    """构建工具列表。

    fail_search / fail_read 用于测试工具失败场景：置 True 时对应工具抛异常。
    """

    @tool
    def search_documents(query: str) -> str:
        """检索知识库，返回与 query 相关的文档列表（含 doc_id、标题、版本日期、摘要）。

        当需要查找某条制度/规定、或不确定答案在哪份文档时，应先调用本工具。
        """
        if fail_search:
            raise RuntimeError("search_documents 服务暂时不可用（模拟故障）")
        results = kb.search(query)
        if not results:
            return "检索结果为空：未找到与问题相关的文档。"
        lines = []
        for r in results:
            lines.append(
                f"- [{r['doc_id']}] {r['title']} (版本日期 {r['version_date']}, "
                f"适用范围 {r['scope']}, 优先级: {r['priority']})\n  摘要: {r['snippet']}"
            )
        return "\n".join(lines)

    @tool
    def read_document(doc_id: str) -> str:
        """读取指定文档的完整原文。参数 doc_id 为文档编号（如 D01）。

        当检索摘要不足以给出确定答案、需要核对原文、或发现多条结果可能冲突时调用。
        """
        if fail_read:
            raise RuntimeError("read_document 服务暂时不可用（模拟故障）")
        doc = kb.read(doc_id)
        if doc is None:
            return f"未找到文档 {doc_id}，请确认文档编号是否正确。"
        return (
            f"文档 [{doc['doc_id']}] {doc['title']} (版本 {doc['version']}, "
            f"版本日期 {doc['version_date']})\n适用范围: {doc['scope']}\n"
            f"优先级声明: {doc['priority']}\n\n原文:\n{doc['content']}"
        )

    return [search_documents, read_document]
