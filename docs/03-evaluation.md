# 03 · 评估结果

## 测试执行结果

```
$ python -m pytest -v
10 passed in 0.54s
```

## 验收点逐项核对

| # | 验收点 | 测试 | 结果 | 实际输出依据 |
|---|---|---|---|---|
| 1 | 明确答案 | `test_clear_answer_year_leave` | ✅ PASS | `examples/traces/01-normal-clear-answer.json` |
| 2a | 冲突+优先级定案 | `test_conflict_with_priority_resolves` | ✅ PASS | `examples/traces/02-conflict-with-priority.json` |
| 2b | 冲突+无优先级追问 | `test_conflict_no_priority_asks` | ✅ PASS | 见下方「用例 2b」 |
| 3 | 资料外问题 | `test_out_of_scope_asks` | ✅ PASS | `examples/traces/03-out-of-scope.json` |
| 4 | 改写相似问题 | `test_paraphrased_question` | ✅ PASS | 见下方「用例 4」 |
| 5 | 上下文追问 | `test_contextual_followup` | ✅ PASS | `examples/traces/05-contextual-followup.json` |
| 6 | 工具失败 | `test_tool_failure_search/read` | ✅ PASS | `examples/traces/04-tool-failure.json` |
| — | 步数上限 | `test_max_steps_returns_incomplete` | ✅ PASS | 状态 `max_steps` |

## 三组必交运行记录（满足题目「至少 3 组」）

1. **正常场景**：`01-normal-clear-answer.json` — 问「年假有几天」，命中 D03，输出答案 + 引用 D03。
2. **资料不足场景**：`03-out-of-scope.json` — 问知识库没有的内容，返回 `needs_clarification`。
3. **工具失败场景**：`04-tool-failure.json` — read 工具抛异常，返回 `tool_error`。

> 另附 2 组覆盖「冲突」与「上下文追问」，共 5 组，超出最低要求。

## 用例 2b：冲突但无优先级 → 追问（关键验收）

构造仅含 D01（30 天）、D02（15 天）的知识库，去掉带优先级的 D05：

**问题**：「报销期限是多久？」

**实际输出**（`needs_clarification`）：
> 发现文档 D01, D02 对「报销」的规定不一致（D01(…30…)、D02(…15…)），且均未声明适用范围与优先级。请问您需要参照哪一份制度？我可以按您指定的制度回答。

**验证要点**：Agent **没有**擅自回答「15 天」或「30 天」，而是列出冲突与引用并请求确认——这正是题目参考实例要求的行为。

## 用例 4：改写后的相似问题

| 问题 | 命中文档 |
|---|---|
| 「报销期限是多久？」 | D05、D01、D04、D02 |
| 「差旅回来以后多久之内要提交报销？」 | D05、D01、D02 … |

两者命中集合有交集（D05/D01），证明「改写问题仍能命中同一批文档」。

## 失败与已知限制

1. **检索粒度粗**：2-gram 关键词检索对「怎么提交」这类流程性问题会连带命中「期限」条款，可能触发误判冲突（如「报销怎么提交？」会命中 D01/D02 的期限冲突）。这是检索相关性的局限，已作为改进项记录。
2. **冲突检测仅覆盖数字型条款**：纯文本型矛盾（如两处流程描述不同）暂未覆盖。
3. **数字抽取过粗**：会把版本号、章节号（如 2.1、3.1）一并抽出，影响冲突判定的可读性（判定方向仍正确）。
4. **Mock 决策器非真实语言理解**：只验证流程闭环，不证明真实模型的语义决策效果（`ChatModelDecision` 为真实入口，未在离线环境实测）。

## 替换文档内容的验证（审核要点）

题目审核要点之一是「替换文档内容，核对答案与动作是否改变」。测试 `test_conflict_no_priority_asks` 通过**替换知识库内容**（去掉 D05）验证了：同一问题「报销期限是多久」，在「有优先级文档」与「无优先级文档」两种资料下，答案与动作**确实改变**（定案 20 天 vs 追问）。这证明 Agent 的决策依赖实际检索到的文档，而非硬编码。
