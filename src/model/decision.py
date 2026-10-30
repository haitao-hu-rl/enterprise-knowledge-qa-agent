"""模型决策层：决定 Agent 下一步动作。

提供两种实现：
1. MockDecisionModel（默认，离线可复现）：用规则实现"根据工具观察结果调整动作"的
   ReAct 决策，用于验证流程闭环。它不做"真实的语言理解"，仅演示决策循环的结构。
2. ChatModelDecision（可选）：接入真实 LLM（langchain-openai 兼容接口），需设置环境变量。

边界说明（重要）：Mock 只验证流程与工具编排是否成立，不证明真实模型的语言理解与
决策效果；真实模型入口见 ChatModelDecision，需配置 OPENAI_API_KEY 等变量。
"""
from __future__ import annotations

import json
import os
from typing import Any, Literal

Action = Literal["search", "read", "ask", "finish"]


class DecisionModel:
    """决策器抽象接口：给定对话状态，输出下一个动作。"""

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MockDecisionModel(DecisionModel):
    """离线 Mock 决策器：用显式规则模拟 ReAct 决策。

    决策逻辑（体现"观察结果 -> 调整下一步"）：
    - 若尚未检索 -> search(用户问题)
    - 检索后：
        * 无结果 -> ask（追问补充信息），或 finish 并标注"资料缺口"
        * 有结果但存在疑似冲突（多条不同期限数字）-> read 关键文档核对原文
        * 有唯一结果 -> read 该文档确认原文
    - 读取后：
        * 发现与已读文档冲突且均无优先级 -> ask（请用户确认适用制度）
        * 发现有优先级声明的文档 -> finish（以高优先级文档为准）
        * 单一文档无冲突 -> finish（给出答案 + 引用）
    - 上下文追问：若用户消息是代词/省略（如"那差旅呢"），先基于历史补全后 search。
    """

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        step = state.get("step", 0)
        observations = state.get("observations", [])
        question = state.get("question", "")
        max_steps = state.get("max_steps", 8)

        # 第一步：总是先检索。
        # 若问题是代词/省略式追问（如"那差旅呢？"），先结合对话历史补全检索词，
        # 提升命中率（对应验收点"上下文追问"与"改写后的相似问题"）。
        if step == 0:
            query = _resolve_contextual_query(question, state.get("history", []))
            return {"action": "search", "args": {"query": query}}

        # 检索之后 / 读取之后：根据最近一次观察决定
        last = observations[-1] if observations else {}

        # 情形 0：工具失败 -> 返回明确的失败状态（不静默给出空答案）
        if last.get("result") == "ERROR":
            failed_tool = last.get("tool", "")
            return {
                "action": "finish",
                "args": {
                    "status_override": "tool_error",
                    "answer": (
                        f"抱歉，工具「{failed_tool}」调用失败：{last.get('output', '')}\n"
                        "本次无法给出可靠回答，请稍后重试，或换个说法再问一次。"
                    ),
                },
            }

        # 情形 1：检索结果为空 -> 追问或判定资料缺口
        if last.get("tool") == "search" and last.get("result") == "EMPTY":
            return {
                "action": "ask",
                "args": {
                    "clarification": (
                        "未能在知识库中找到与您问题相关的文档。请问您能补充一些关键词，"
                        "例如具体制度名称、业务场景或文档编号吗？"
                    )
                },
            }

        # 情形 2：检索到结果但尚未读原文 -> 读关键文档（优先读最高分文档）
        if last.get("tool") == "search" and last.get("result") == "HITS":
            top_doc = _top_doc_id(last)
            return {"action": "read", "args": {"doc_id": top_doc}}

        # 情形 3：读取了文档 -> 决定是否需要补充查证，还是结束
        if last.get("tool") == "read":
            return self._after_read(state)

        # 兜底：停止
        return {"action": "finish", "args": {}}

    def _candidate_docs(self, state: dict[str, Any]) -> list[str]:
        """从最近一次 search 观察中取回候选文档 ID 列表（跨节点实时推导，不依赖状态持久化）。"""
        for o in reversed(state.get("observations", [])):
            if o.get("tool") == "search" and o.get("result") == "HITS":
                return [d["doc_id"] for d in o.get("docs", [])]
        return []

    def _after_read(self, state: dict[str, Any]) -> dict[str, Any]:
        step = state.get("step", 0)
        max_steps = state.get("max_steps", 8)
        observations = state.get("observations", [])
        read_docs = [o for o in observations if o.get("tool") == "read"]
        if not read_docs:
            return {"action": "finish", "args": {}}

        # 3a. 先检测已读文档之间是否冲突（优先于继续查证）
        conflict = _detect_conflict(read_docs)
        if conflict is not None:
            conflicted_ids = conflict["doc_ids"]
            # 检查是否有高优先级文档可定案
            high_priority = _find_priority_doc(state, conflicted_ids)
            if high_priority:
                # 有优先级文档 -> 以该文档为准，列出冲突并说明定案依据
                pri_doc = self._get_doc(state, high_priority)
                answer = (
                    f"知识库中存在关于「{conflict['topic']}」的冲突：\n"
                    f"  {conflict['values']}\n"
                    f"其中文档 [{high_priority}] 声明了优先级（{conflict['priority_note']}），"
                    f"按规则以该文档为准。\n\n"
                    f"结论：{_extract_answer(state['question'], pri_doc)}"
                )
                return {
                    "action": "finish",
                    "args": {
                        "answer": answer,
                        "citations": [
                            {
                                "doc_id": high_priority,
                                "quote": pri_doc.get("quote", ""),
                            }
                        ],
                    },
                }
            # 无优先级文档 -> 不能擅自选一个，请求确认
            return {
                "action": "ask",
                "args": {
                    "clarification": (
                        f"发现文档 {', '.join(conflicted_ids)} 对「{conflict['topic']}」"
                        f"的规定不一致（{conflict['values']}），且均未声明适用范围与优先级。"
                        "请问您需要参照哪一份制度？我可以按您指定的制度回答。"
                    )
                },
            }

        # 3b. 无冲突：若还有未读候选文档，继续读下一篇以查证是否遗漏冲突
        read_ids = {o["args"].get("doc_id") for o in read_docs}
        candidates = self._candidate_docs(state)
        unread = [c for c in candidates if c not in read_ids]
        checked = len(read_docs)
        if unread and checked <= 3 and step < max_steps - 1:
            return {"action": "read", "args": {"doc_id": unread[0]}}

        # 3c. 无冲突且已查证完毕：基于已读文档给出答案
        doc = read_docs[-1]
        meta = doc.get("meta", {})
        return {
            "action": "finish",
            "args": {
                "answer": _extract_answer(state["question"], doc),
                "citations": [
                    {
                        "doc_id": meta.get("doc_id", doc.get("doc_id", "")),
                        "quote": doc.get("quote", ""),
                    }
                ],
            },
        }

    def _get_doc(self, state: dict[str, Any], doc_id: str) -> dict:
        for o in state["observations"]:
            if o.get("tool") == "read" and o.get("meta", {}).get("doc_id") == doc_id:
                return o
        return {}


def _top_doc_id(observation: dict) -> str:
    docs = observation.get("docs", [])
    return docs[0]["doc_id"] if docs else ""


def _resolve_contextual_query(question: str, history: list[dict[str, str]]) -> str:
    """上下文追问时的检索词补全。

    当问题很短且含代词/追问语气词（"那""它""这个""呢"）时，说明用户在做省略式追问，
    此时把上一条用户问题拼接到当前问题前，作为更完整的检索词。
    """
    followup_markers = ["那", "它", "这个", "那个", "呢", "还有", "这些"]
    if len(question) <= 8 and any(m in question for m in followup_markers):
        # 从历史中取最近的用户消息（history 结构：[{role, content}, ...]）
        prev_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                prev_user = msg.get("content", "")
                break
        if prev_user and prev_user not in question:
            return f"{prev_user} {question}"
    return question


def _detect_conflict(read_docs: list[dict]) -> dict | None:
    """检测多篇文档针对同一主题的数字型结论是否冲突。

    简化实现：抽取文档中的数字，若针对相同关键词（如"期限/天"）出现不同数字即视为冲突。
    read_docs 中的每个 observation 含 meta（doc_id/title/content/priority）与 quote。
    """
    import re

    topic_keywords = ["报销", "期限", "年假", "住宿", "到账", "审批", "标准"]
    entries = []  # (doc_id, topic, numbers, priority, quote)
    for d in read_docs:
        meta = d.get("meta", {})
        content = d.get("content", meta.get("content", ""))
        title = meta.get("title", "")
        doc_id = meta.get("doc_id", "")
        priority = meta.get("priority", "")
        for kw in topic_keywords:
            if kw in title or kw in content:
                nums = re.findall(r"\d+(?:\.\d+)?", content)
                entries.append((doc_id, kw, nums, priority, d.get("quote", "")))
                break

    # 比较同主题文档的数字
    from collections import defaultdict

    by_topic: dict[str, list] = defaultdict(list)
    for doc_id, kw, nums, priority, quote in entries:
        by_topic[kw].append((doc_id, nums, priority, quote))

    for kw, items in by_topic.items():
        if len(items) >= 2:
            numeric_sets = [set(n for n in nums if n.isdigit()) for _, nums, _, _ in items]
            # 若两篇文档存在互不相同的数字，视为冲突
            first = numeric_sets[0]
            for s in numeric_sets[1:]:
                if s and first and s != first:
                    # 只收集"真正声明优先级"的文档（含"为准/最新/优先于"等关键词）
                    priority_notes = [
                        p
                        for _, _, p, _ in items
                        if p and any(k in p for k in ["为准", "最新", "高于", "以本", "以该", "优先于"])
                    ]
                    return {
                        "topic": kw,
                        "doc_ids": [doc_id for doc_id, _, _, _ in items],
                        "values": "、".join(
                            f"{doc_id}({'/'.join(sorted(nums))})"
                            for doc_id, nums, _, _ in items
                        ),
                        "priority_note": "; ".join(priority_notes) if priority_notes else "",
                    }
    return None


def _find_priority_doc(state: dict, conflicted_ids: list[str]) -> str | None:
    """在冲突文档中查找"真正声明优先级"的文档，用于定案。

    关键：优先级的判定必须是"积极声明"（如"以本说明为准/最新口径/优先级高于"），
    而非"无/未声明优先级"这种消极表述。题目参考实例强调：无优先级时不得擅自选一个。
    """
    negative_markers = ["无", "未", "不", "没有"]
    positive_markers = ["为准", "最新", "高于", "以本", "以该", "优先于"]
    for o in state["observations"]:
        if o.get("tool") == "read":
            meta = o.get("meta", {})
            if meta.get("doc_id") in conflicted_ids:
                pri = meta.get("priority", "")
                # 先排除"明确表示无优先级"的文档
                if any(n in pri for n in negative_markers) and not any(
                    p in pri for p in positive_markers
                ):
                    continue
                # 再判定是否积极声明了优先级
                if any(p in pri for p in positive_markers):
                    return meta["doc_id"]
    return None


def _extract_answer(question: str, doc: dict) -> str:
    meta = doc.get("meta", {})
    doc_id = meta.get("doc_id", doc.get("doc_id", "?"))
    title = meta.get("title", doc.get("title", ""))
    content = doc.get("content", meta.get("content", ""))
    return (
        f"根据文档 [{doc_id}] {title}：\n"
        f"{content[:200]}"
    )


class ChatModelDecision(DecisionModel):
    """接入真实 LLM 的决策器（可选）。

    通过 langchain-openai 兼容接口调用模型，让模型根据对话历史与工具观察自主选择
    下一个动作。需设置 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL。
    """

    def __init__(self):
        from langchain_openai import ChatOpenAI  # 延迟导入，避免无依赖时失败

        self.llm = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "你是企业知识问答 Agent 的决策器。根据下面的对话状态，选择下一个动作，"
            "动作只能是 search / read / ask / finish 之一，并给出参数 JSON。\n\n"
            f"对话状态：{json.dumps(state, ensure_ascii=False, default=str)}"
        )
        resp = self.llm.invoke(prompt)
        return json.loads(resp.content)
