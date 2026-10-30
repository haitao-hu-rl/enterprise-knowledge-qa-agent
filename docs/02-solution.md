# 02 · 解决方案说明

## 调用流程（StateGraph）

```
START
  │
  ▼
[decide]  ──模型选择动作──▶ search / read / ask / finish
  │                              │
  │◀──────────── 观察结果 ────────┤
  │                              
  ▼  ask ──▶ [clarify] ──▶ END
  ▼  finish ─▶ [finish]  ─▶ END
```

节点说明：
- **decide**：调用决策器，根据当前状态（步数、历史、已有观察）输出下一个动作。
- **execute**：执行 `search_documents` / `read_document`，把工具返回**摘要 + 结构化字段**写入 `observations`；工具异常时记录为 `ERROR`（不中断）。
- **clarify**：产出追问文案，状态 `needs_clarification`。
- **finish**：产出最终答案 + 引用，状态 `answered` / `tool_error`。

## 动态决策（核心：根据工具结果调整动作）

决策器 `MockDecisionModel.decide` 的关键分支（完整代码 `src/model/decision.py`）：

| 当前观察 | 决策动作 | 依据 |
|---|---|---|
| 尚无观察 | `search(question)` | 先从检索入手 |
| search 返回 EMPTY | `ask`（追问） | 判定资料缺口 |
| search 返回 HITS | `read(最高分文档)` | 摘要不足以给确定答案，读原文 |
| read 后、有未读候选且无冲突 | 继续 `read(下一篇)` | **补充查证**，避免漏掉冲突 |
| read 后检测到冲突 + 有优先级文档 | `finish`（列冲突 + 以优先级文档定案） | 有权威口径可定案 |
| read 后检测到冲突 + 无优先级 | `ask`（请用户确认适用制度） | 不能擅自选一个 |
| read 后无冲突且查证完毕 | `finish`（答案 + 引用） | 有原文支撑 |

**冲突检测逻辑**：抽取已读文档中的「数字型条款」，若针对同一主题（如「报销/期限」）出现不同数字即视为冲突。冲突定案时，先判定是否存在「积极声明优先级」的文档（含「为准/最新/以本/高于/优先于」等词），**排除「无/未声明优先级」这种消极表述**——这正是题目参考实例强调的「不能擅自回答 15 天」的关键。

**上下文追问**：问题很短且含代词/追问语气词（"那""它""呢"等）时，把历史最近一条用户消息拼接到检索词前，提升命中率。

## 步数上限

LangGraph 的 `recursion_limit` 设为 `max_steps + 2`（默认 8 步）。当循环步数超限时捕获 `GraphRecursionError`，返回状态 `max_steps` 与明确的「任务未完成」文案。决策器内部也会在步数逼近上限时停止继续查证、直接进入结论判断，避免无谓消耗。

## 技术取舍

### 为什么用 LangGraph，而不是手写 while 循环？

- **显式状态机**：节点/边/条件路由清晰表达 ReAct 循环，评审可读。
- **工具调用协议**：复用 `langchain_core.tools.@tool` 的入参校验与序列化，减少样板代码。
- **内置步数上限**：`recursion_limit` 天然满足考核「执行步数上限」要求，不用自己计数。

### 为什么自实现决策循环，而不直接用 `create_react_agent`？

- `create_react_agent` 依赖真实 LLM 驱动，无法离线运行；而考核要求「模型不可用时提供离线 Mock 入口」。
- 自实现 `DecisionModel` 抽象让「Mock 决策器」与「真实 LLM 决策器」可互换，**离线也能证明决策闭环**。
- 冲突检测、优先级定案这些**业务规则**需要自己写，框架的 prebuilt 不包含这些领域逻辑。

### 为什么模型与工具解耦？

`DecisionModel` 接口隔离了「决策」与「执行」，好处是：
1. 离线 Mock 验证流程闭环；
2. 真实模型接入只需实现 `ChatModelDecision`，不改 Agent 与工具；
3. 评审可清楚看到「哪些是框架能力、哪些是个人实现」。

### 为什么用朴素 2-gram 检索而不是向量检索？

离线可复现、零外部依赖是首要目标（评审可直接跑）。检索本身不是本题考核重点，冲突处理与检索改进才是。已在 `05-retrospective.md` 记录向量化作为下一步改进。

## 关键实现文件

| 文件 | 职责 |
|---|---|
| `src/agent/agent.py` | LangGraph 状态机、节点、`run()` 入口、步数上限 |
| `src/model/decision.py` | 决策器（Mock + ChatModel）、冲突检测、优先级判定、上下文补全 |
| `src/tools/knowledge_base.py` | 知识库、检索、片段读取 |
| `src/tools/tools.py` | 工具封装 + 故障注入 |
| `src/main.py` | CLI 入口 |
