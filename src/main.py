"""CLI 入口：从命令行运行企业知识问答 Agent。

用法：
    python -m src.main --question "报销期限是多久？"
    python -m src.main --question "报销期限是多久？" --use-chat-model   # 需配置 OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from src.agent.agent import KnowledgeQAAgent
from src.model.decision import ChatModelDecision, MockDecisionModel
from src.tools.knowledge_base import KnowledgeBase

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "faq_documents.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="企业知识问答 Agent")
    parser.add_argument("--question", required=True, help="要回答的问题")
    parser.add_argument("--max-steps", type=int, default=8, help="最大执行步数")
    parser.add_argument("--use-chat-model", action="store_true", help="使用真实 LLM（需配置 OPENAI_API_KEY）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结构化结果")
    args = parser.parse_args()

    kb = KnowledgeBase.from_json(DATA_FILE)
    model = ChatModelDecision() if args.use_chat_model else MockDecisionModel()
    agent = KnowledgeQAAgent(kb, model, max_steps=args.max_steps)

    result = agent.run(args.question)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"问题: {result['question']}")
        print(f"状态: {result['status']}")
        print(f"回答: {result['final_answer']}")
        if result.get("citations"):
            print("引用:")
            for c in result["citations"]:
                print(f"  - {c}")
        print(f"\n执行轨迹（{len(result['observations'])} 步）:")
        for o in result["observations"]:
            print(f"  [{o['step']}] {o['tool']}({o['args']}) -> {o['result']}")
            out = o.get("output", "")
            if out:
                print(f"      输出: {out[:80]}{'…' if len(out) > 80 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
