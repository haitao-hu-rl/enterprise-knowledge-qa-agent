# 01 · 需求说明

## 用户与目标

**用户**：企业内部员工，需要快速、可靠地查到制度/产品问题的答案，避免凭印象或过时口径作答。

**目标**：构建一个「企业知识问答 Agent」，对用户问题返回**有依据、可追溯**的答案。

## 范围（Scope）

- **输入**：用户问题 + 可选对话历史（支持多轮上下文追问）。
- **材料**：带文档 ID、版本日期、适用范围、优先级声明的合成 FAQ/制度（`data/faq_documents.json`）。
- **工具**：
  1. `search_documents`：关键词检索，返回候选文档列表（含 doc_id、标题、版本日期、摘要）。
  2. `read_document`：读取指定文档完整原文与元信息。
- **交付结果**：回答 + 引用文档 ID + 原文片段 + 资料缺口 + 任务状态。

## 非目标（Non-goals）

- 不做前端界面、不做线上部署（考核规则明确非必需）。
- 不做多 Agent 协作、生产级 Runtime。
- 检索不做真实向量化（用本地可复现的关键词检索演示，注明边界）。

## 成功标准

1. **明确答案**：单一权威文档时，直接给出答案并附文档 ID + 原文引用。
2. **文档冲突**：多篇文档对同一问题给出矛盾结论时，**列出冲突与引用**，并：
   - 若有文档声明优先级/适用范围 → 说明冲突并以该文档定案；
   - 若均无优先级 → **追问用户确认适用制度，绝不擅自选一个**。
3. **资料外问题**：知识库无相关内容时，明确返回「资料缺口」并追问。
4. **改写相似问题**：同一问题换说法仍能命中正确文档。
5. **上下文追问**：代词/省略式追问能结合历史补全检索。
6. **工具失败**：工具抛异常时，返回明确的失败状态，不给出无依据回答。
7. **步数上限**：达到执行步数上限时，返回明确的「未完成」状态。

## 验收点 → 测试/用例映射

| 验收点 | 测试 | Trace |
|---|---|---|
| 明确答案 | `test_clear_answer_year_leave` | `01-normal-clear-answer.json` |
| 文档冲突（优先级定案） | `test_conflict_with_priority_resolves` | `02-conflict-with-priority.json` |
| 文档冲突（无优先级追问） | `test_conflict_no_priority_asks` | 见 `docs/03-evaluation.md` |
| 资料外问题 | `test_out_of_scope_asks` | `03-out-of-scope.json` |
| 改写相似问题 | `test_paraphrased_question` | 见 `docs/03-evaluation.md` |
| 上下文追问 | `test_contextual_followup` | `05-contextual-followup.json` |
| 工具失败 | `test_tool_failure_search/read` | `04-tool-failure.json` |
| 步数上限 | `test_max_steps_returns_incomplete` | — |
