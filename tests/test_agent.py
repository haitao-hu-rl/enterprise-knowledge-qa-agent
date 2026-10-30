"""企业知识问答 Agent 的可执行测试。

覆盖题目要求的全部 6 个验收点：
1. 明确答案（正常场景）
2. 文档冲突（含优先级定案 / 无优先级追问两条子路径）
3. 资料外问题（无结果 -> 追问）
4. 改写后的相似问题（同一问题换说法仍能命中）
5. 上下文追问（代词/省略 + 历史补全）
6. 工具失败（search / read 抛异常 -> tool_error 状态）

运行方式：
    python -m pytest tests/ -v
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.agent import KnowledgeQAAgent
from src.model.decision import MockDecisionModel
from src.tools.knowledge_base import Document, KnowledgeBase

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "faq_documents.json"


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_json(DATA)


@pytest.fixture()
def agent(kb):
    return KnowledgeQAAgent(kb, MockDecisionModel())


# ---------- 验收点 1：明确答案（正常场景） ----------

def test_clear_answer_year_leave(agent):
    """问年假天数，应命中 D03 并给出明确答案 + 引用。"""
    r = agent.run("年假有几天？")
    assert r["status"] == "answered"
    assert "5 天" in r["final_answer"]
    assert r["citations"], "应包含文档引用"
    assert r["citations"][0]["doc_id"] == "D03"


def test_clear_answer_cites_source(agent):
    """回答必须带文档 ID 引用。"""
    r = agent.run("年假有几天？")
    assert any(c["doc_id"] for c in r["citations"])


# ---------- 验收点 2：文档冲突 ----------

def test_conflict_with_priority_resolves(agent):
    """D05（优先级）vs D01，应列出冲突并以 D05 为准（20 天），而非擅自选 30 天。"""
    r = agent.run("报销期限是多久？")
    assert r["status"] == "answered"
    assert "冲突" in r["final_answer"]
    assert "20 天" in r["final_answer"]
    assert "D05" in r["final_answer"]
    assert r["citations"][0]["doc_id"] == "D05"


def test_conflict_no_priority_asks(agent):
    """D01(30天) vs D02(15天) 均无优先级，必须追问而非擅自回答。"""
    # 构造仅含 D01/D02 的知识库（去掉带优先级的 D05），模拟"无优先级冲突"
    docs = [d for d in _load_docs() if d["doc_id"] in ("D01", "D02")]
    kb2 = KnowledgeBase([Document(**d) for d in docs])
    a2 = KnowledgeQAAgent(kb2, MockDecisionModel())
    r = a2.run("报销期限是多久？")
    assert r["status"] == "needs_clarification"
    assert "冲突" in r["final_answer"] or "不一致" in r["final_answer"]
    assert "D01" in r["final_answer"] and "D02" in r["final_answer"]
    # 关键：不能给出"15天"或"30天"作为确定答案
    assert "15 天" not in r["final_answer"] or "不一致" in r["final_answer"]


# ---------- 验收点 3：资料外问题 ----------

def test_out_of_scope_asks(agent):
    """问知识库没有的内容，应返回 needs_clarification / 资料缺口。"""
    r = agent.run("公司附近有什么好吃的餐厅？")
    assert r["status"] == "needs_clarification"
    assert "未能在知识库中找到" in r["final_answer"]


# ---------- 验收点 4：改写后的相似问题 ----------

def test_paraphrased_question(agent):
    """同一问题换说法（"报销期限" vs "差旅报销多久提交"），仍应命中相关文档。"""
    r1 = agent.run("报销期限是多久？")
    r2 = agent.run("差旅回来以后多久之内要提交报销？")
    # 两个改写问题都应检索到 D01 或 D05 相关文档
    ids1 = _hit_ids(r1)
    ids2 = _hit_ids(r2)
    assert ids1 and ids2, "改写问题应能检索到文档"
    assert bool(set(ids1) & set(ids2)), "改写前后应命中共同文档"


# ---------- 验收点 5：上下文追问 ----------

def test_contextual_followup(agent):
    """代词/省略追问应结合历史补全检索词。"""
    history = [
        {"role": "user", "content": "报销期限是多久？"},
        {"role": "assistant", "content": "20 天"},
    ]
    r = agent.run("那差旅标准呢？", history=history)
    # 检索词应包含历史主题
    query = r["observations"][0]["args"]["query"]
    assert "报销" in query or "差旅" in query


# ---------- 验收点 6：工具失败 ----------

def test_tool_failure_search(kb):
    a = KnowledgeQAAgent(kb, MockDecisionModel(), fail_search=True)
    r = a.run("报销期限是多久？")
    assert r["status"] == "tool_error"
    assert "失败" in r["final_answer"]


def test_tool_failure_read(kb):
    a = KnowledgeQAAgent(kb, MockDecisionModel(), fail_read=True)
    r = a.run("年假有几天？")
    assert r["status"] == "tool_error"
    assert "失败" in r["final_answer"]


# ---------- 步数上限 ----------

def test_max_steps_returns_incomplete(kb):
    """步数上限达到时应返回明确的未完成状态。"""
    a = KnowledgeQAAgent(kb, MockDecisionModel(), max_steps=1)
    r = a.run("报销期限是多久？")
    assert r["status"] == "max_steps"
    assert "未完成" in r["final_answer"]


# ---------- 辅助 ----------

def _load_docs():
    with open(DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def _hit_ids(result):
    ids = set()
    for o in result["observations"]:
        for d in o.get("docs", []):
            ids.add(d["doc_id"])
    return ids
