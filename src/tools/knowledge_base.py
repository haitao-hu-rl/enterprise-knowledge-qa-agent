"""知识库工具层：文档检索与片段读取。

本模块提供 Agent 可调用的两个工具：
1. search_documents: 基于关键词的文档检索（本地实现，模拟向量检索/BM25）。
2. read_document: 读取指定文档的原文片段。

工具均设计为可注入 `fail_*` 开关，用于模拟工具失败场景（对应验收点"工具失败"）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Document:
    doc_id: str
    title: str
    version: str
    version_date: str
    scope: str
    priority: str
    content: str


class KnowledgeBase:
    """内存中的合成知识库，从 JSON 加载。"""

    def __init__(self, documents: list[Document]):
        self._docs = {d.doc_id: d for d in documents}

    @classmethod
    def from_json(cls, path: str | Path) -> "KnowledgeBase":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        docs = [Document(**item) for item in raw]
        return cls(docs)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """朴素关键词检索：按命中关键词数量 + 标题相关度打分。

        返回结果包含 doc_id、标题、版本日期、匹配摘要，供模型判断下一步动作。
        """
        keywords = _tokenize(query)
        scored: list[tuple[float, Document]] = []
        for doc in self._docs.values():
            score = 0.0
            title_hits = sum(1 for kw in keywords if kw in doc.title)
            content_hits = sum(1 for kw in keywords if kw in doc.content)
            score += title_hits * 2.0 + content_hits * 1.0
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            results.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "version_date": doc.version_date,
                    "scope": doc.scope,
                    "priority": doc.priority,
                    "score": round(score, 2),
                    "snippet": _make_snippet(doc.content, keywords),
                }
            )
        return results

    def read(self, doc_id: str) -> Optional[dict]:
        """读取单篇文档的完整原文与元信息。"""
        doc = self._docs.get(doc_id)
        if doc is None:
            return None
        return {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "version": doc.version,
            "version_date": doc.version_date,
            "scope": doc.scope,
            "priority": doc.priority,
            "content": doc.content,
        }

    def all_ids(self) -> list[str]:
        return list(self._docs.keys())


def _tokenize(text: str) -> set[str]:
    """极简中文分词：按 2-gram 切分 + 保留常见关键词。

    生产环境应替换为 jieba / 向量检索，这里仅为离线可复现的演示实现。
    """
    text = text.strip()
    grams = set()
    for i in range(len(text) - 1):
        grams.add(text[i : i + 2])
    # 补充几个常见业务关键词，提升检索召回
    for kw in ["报销", "期限", "年假", "差旅", "发票", "到账", "住宿", "审批"]:
        if kw in text:
            grams.add(kw)
    return grams


def _make_snippet(content: str, keywords: set[str], width: int = 40) -> str:
    """截取命中关键词附近的片段作为检索摘要。"""
    for kw in keywords:
        idx = content.find(kw)
        if idx >= 0:
            start = max(0, idx - width // 2)
            end = min(len(content), idx + width)
            return content[start:end] + ("…" if end < len(content) else "")
    return content[:width] + ("…" if len(content) > width else "")
