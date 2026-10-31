# 企业知识问答 Agent

> 企业知识问答 Agent：基于 LangGraph 的 ReAct 决策循环，支持文档检索、冲突检测与溯源引用（小影校招 AI Agent 开发岗考核项目）

> 小影校招 AI Agent 开发岗考核项目 · 题号：**企业知识问答 Agent**

帮助员工找到制度或产品问题的可靠答案，实现「模型选择动作 → 执行工具 → 观察结果 → 调整下一步」的 ReAct 决策循环，并在回答中给出**文档引用、原文片段、资料缺口与任务状态**。

---

## 一句话思路

用 **LangGraph** 管理 ReAct 状态机：Agent 先检索 → 读原文核对 → 发现冲突时**补充查证**并用「优先级/适用范围」定案，或**追问用户**（绝不擅自选一个答案）；全程记录 Trace，步数超限返回明确的未完成状态。

## 评审入口（从这里开始看）

| 想了解什么 | 去哪里 |
|---|---|
| 怎么跑起来 | 本文档「运行方式」 |
| 需求与成功标准 | `docs/01-requirements.md` |
| 调用流程与动态决策、技术取舍 | `docs/02-solution.md` |
| 测试预期与实际结果 | `docs/03-evaluation.md` |
| AI 使用范围与个人贡献 | `docs/04-ai-usage.md` |
| 最难问题与学习收获 | `docs/05-retrospective.md` |
| 实际运行记录（Trace） | `examples/traces/`（含 5 组场景） |
| 核心代码 | `src/` |

---

## 环境与安装

- Python **3.11+**（本项目在 3.13 上验证通过）
- 依赖：`langgraph`、`langchain-core`、`langchain-openai`（仅真实模型需要）

```bash
# 1. 克隆仓库
git clone <your-repo-url> && cd <repo>

# 2. （可选）创建虚拟环境
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt
```

> 默认使用**离线 Mock 决策器**，**无需任何环境变量或 API Key** 即可运行。
> 只有接入真实 LLM 时才需要配置 `.env`（见 `.env.example`）。

## 运行方式（CLI）

```bash
# 单个问题（默认离线 Mock 决策器）
python -m src.main --question "报销期限是多久？"

# 结构化 JSON 输出（含完整 Trace）
python -m src.main --question "年假有几天？" --json

# 指定最大执行步数
python -m src.main --question "报销期限是多久？" --max-steps 6

# 接入真实 LLM（需先配置 OPENAI_API_KEY）
python -m src.main --question "报销期限是多久？" --use-chat-model
```

## 运行测试

```bash
python -m pytest -v
```

测试覆盖全部 6 个验收点（见 `tests/test_agent.py`）。

## 重新生成 Trace

```bash
python examples/generate_traces.py
```

---

## 项目结构

```
.
├── README.md                 # 本文件
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量示例（默认无需配置）
├── pytest.ini                # 测试配置
├── src/
│   ├── main.py               # CLI 入口
│   ├── agent/agent.py        # LangGraph ReAct 状态机
│   ├── model/decision.py     # 决策器（Mock + 真实 LLM 两种）
│   └── tools/
│       ├── knowledge_base.py # 检索/读取知识库实现
│       └── tools.py          # LangChain 工具封装 + 故障注入
├── tests/
│   └── test_agent.py         # 10 个测试，覆盖 6 验收点
├── examples/
│   ├── generate_traces.py    # Trace 生成脚本
│   └── traces/               # 5 组实际运行记录
├── data/
│   └── faq_documents.json    # 合成 FAQ/制度（含冲突用例）
└── docs/                     # 5 份设计文档
```

## 技术栈与版本

| 组件 | 版本 | 承担职责 |
|---|---|---|
| LangGraph | 1.2.x | ReAct 状态机、工具调用协议、`recursion_limit` 步数上限 |
| langchain-core | 1.7.x | 工具抽象（`@tool` 装饰器）、消息协议 |
| langchain-openai | 1.7.x | 真实 LLM 接入（可选） |
| pytest | 9.x | 可执行测试 |

> 说明：本项目**自实现 ReAct 决策循环与冲突检测逻辑**，仅使用 LangGraph 的状态图编排能力，未依赖 `langgraph.prebuilt.create_react_agent`（详见 `docs/02-solution.md` 的技术取舍）。

## 已知限制

- 检索为朴素 2-gram 关键词匹配，未使用向量检索（演示用，生产可替换为 embedding + 向量库）。
- 冲突检测针对「数字型条款」，对纯文本型冲突（如流程描述矛盾）覆盖有限。
- 默认 Mock 决策器只验证**流程闭环**，不证明真实模型的语言理解效果（真实模型入口见 `ChatModelDecision`）。
