"""生成 examples/traces/ 下的运行记录（Trace）。

运行三组代表性场景，输出完整 JSON Trace（含步骤、工具参数、返回摘要、后续动作）。
这些 Trace 被 docs/03-evaluation.md 引用，作为"模型根据工具结果调整动作"的证据。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.agent import KnowledgeQAAgent
from src.model.decision import MockDecisionModel
from src.tools.knowledge_base import KnowledgeBase

DATA = ROOT / "data" / "faq_documents.json"
TRACE_DIR = ROOT / "examples" / "traces"


def build_trace(result: dict, title: str, scenario: str) -> dict:
    """把运行结果整理为带决策依据的可读 Trace。"""
    steps = []
    for o in result["observations"]:
        tool = o["tool"]
        args = o["args"]
        output = o.get("output", "")
        summary = _summarize(output)
        steps.append(
            {
                "step": o["step"],
                "action": tool,
                "tool_params": args,
                "result_type": o.get("result", ""),
                "return_summary": summary,
            }
        )
    # 最终动作
    final_action = "finish" if result["status"] == "answered" else (
        "ask" if result["status"] == "needs_clarification" else result["status"]
    )
    return {
        "scenario": scenario,
        "title": title,
        "question": result["question"],
        "final_status": result["status"],
        "final_answer": result["final_answer"],
        "citations": result["citations"],
        "decision_rationale": _rationale(result),
        "steps": steps,
    }


def _summarize(output: str) -> str:
    if not output:
        return ""
    return output[:120] + ("…" if len(output) > 120 else "")


def _rationale(result: dict) -> str:
    """简要记录每一步的决策依据（不含模型内部思维过程）。"""
    notes = []
    for o in result["observations"]:
        tool = o["tool"]
        if tool == "search":
            if o.get("result") == "EMPTY":
                notes.append("检索无结果 -> 判定资料不足，选择追问")
            else:
                n = len(o.get("docs", []))
                notes.append(f"检索命中 {n} 篇 -> 选择读取最高分文档核对原文")
        elif tool == "read":
            notes.append(f"读取原文 -> 根据内容决定定案/继续查证/追问")
    status = result["status"]
    if status == "answered" and result.get("citations"):
        notes.append("确认答案有原文支持 -> 输出回答并附引用")
    elif status == "needs_clarification":
        notes.append("发现冲突且无优先级/资料不足 -> 请求用户确认")
    elif status == "tool_error":
        notes.append("工具失败 -> 返回明确失败状态，不给出无依据回答")
    return "；".join(notes)


def main():
    kb = KnowledgeBase.from_json(DATA)

    # 场景 1：正常答案（明确回答 + 引用）
    agent = KnowledgeQAAgent(kb, MockDecisionModel())
    r1 = agent.run("年假有几天？")
    trace1 = build_trace(r1, "正常场景-明确答案", "normal")

    # 场景 2：文档冲突（优先级定案）
    r2 = agent.run("报销期限是多久？")
    trace2 = build_trace(r2, "文档冲突-优先级定案", "conflict")

    # 场景 3：资料外问题
    r3 = agent.run("公司健身房怎么预约？")
    trace3 = build_trace(r3, "资料外问题-追问", "out_of_scope")

    # 场景 4：工具失败
    agent_fail = KnowledgeQAAgent(kb, MockDecisionModel(), fail_read=True)
    r4 = agent_fail.run("年假有几天？")
    trace4 = build_trace(r4, "工具失败-read异常", "tool_failure")

    # 场景 5：上下文追问
    history = [
        {"role": "user", "content": "报销期限是多久？"},
        {"role": "assistant", "content": "20 天"},
    ]
    r5 = agent.run("那差旅标准呢？", history=history)
    trace5 = build_trace(r5, "上下文追问-历史补全", "contextual_followup")

    traces = [
        ("01-normal-clear-answer.json", trace1),
        ("02-conflict-with-priority.json", trace2),
        ("03-out-of-scope.json", trace3),
        ("04-tool-failure.json", trace4),
        ("05-contextual-followup.json", trace5),
    ]

    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, trace in traces:
        path = TRACE_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        print(f"已生成 {path.relative_to(ROOT)}")

    # 同时生成一个汇总索引
    index = {
        "description": "企业知识问答 Agent 运行记录（Trace）索引",
        "traces": [
            {"file": fn, "scenario": t["scenario"], "title": t["title"]}
            for fn, t in traces
        ],
    }
    with open(TRACE_DIR / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print("已生成 examples/traces/index.json")


if __name__ == "__main__":
    main()
