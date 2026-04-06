# 财务报表问答系统 (Financial RAG) 代码实现方案

本方案基于 `prd.md` 及 `financial_report_rag_schema.jsonc` 设计，旨在为 Claude Code 提供清晰、可执行的工程实现指南。系统采用 FastAPI + React 的前后端分离架构，核心检索与生成逻辑完全遵循 PRD 中定义的“高精度、易部署”本地与在线混合架构。

## 1. 系统架构与技术栈选型

为满足快速迭代与本地部署的需求，系统采用以下技术栈：

*   **后端框架**：FastAPI (Python 3.11+)
*   **前端框架**：React + TypeScript + TailwindCSS (Vite 构建)
*   **向量数据库**：Qdrant (使用 `qdrant-client` 的本地文件模式，无需独立部署 Server) [1]
*   **核心模型**：
    *   **Embedding & Sparse & ColBERT**：`BAAI/bge-m3` (通过 `FlagEmbedding` 库本地运行) [2]
    *   **Cross-Encoder Reranker**：`BAAI/bge-reranker-v2-gemma` (通过 `FlagEmbedding` 库本地运行) [3]
    *   **LLM (摘要与生成)**：智谱 `glm-4-flash` API (通过 `zhipuai` SDK 调用) [4]

## 2. 项目目录结构

为了让 Claude Code 能够顺利构建项目，建议采用以下目录结构：

```text
financial-rag/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── endpoints/
│   │   │   │   ├── documents.py    # 文档上传与索引接口
│   │   │   │   └── chat.py         # 问答交互接口
│   │   │   └── router.py           # 路由注册
│   │   ├── core/
│   │   │   ├── config.py           # 环境变量与配置管理
│   │   │   └── prompts.py          # LLM Prompt 模板集中管理
│   │   ├── models/
│   │   │   └── schemas.py          # Pydantic 数据模型 (基于 JSON Schema)
│   │   ├── services/
│   │   │   ├── indexer.py          # 索引管道逻辑
│   │   │   ├── retriever.py        # 检索管道逻辑
│   │   │   ├── reranker.py         # 重排序逻辑
│   │   │   ├── generator.py        # 答案生成逻辑
│   │   │   └── llm_client.py       # 智谱 API 封装
│   │   ├── utils/
│   │   │   └── qdrant_client.py    # Qdrant 客户端单例封装
│   │   └── main.py                 # FastAPI 应用入口
│   ├── data/                       # 本地数据存储 (Qdrant 数据、上传的 JSON)
│   ├── requirements.txt            # Python 依赖
│   └── .env                        # 环境变量文件 (API Key 等)
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Chat/
│   │   │   │   ├── ChatBox.tsx     # 聊天主界面
│   │   │   │   ├── Message.tsx     # 单条消息组件 (支持 Markdown 和 Citation Badge)
│   │   │   │   └── InputArea.tsx   # 输入框组件
│   │   │   ├── Document/
│   │   │   │   ├── UploadModal.tsx # 文件上传弹窗
│   │   │   │   └── DocList.tsx     # 已索引文档列表
│   │   │   └── Layout/
│   │   │       ├── Sidebar.tsx     # 侧边栏 (文档管理 + 历史会话)
│   │   │       └── Header.tsx      # 顶部导航栏
│   │   ├── hooks/
│   │   │   └── useChat.ts          # 封装 SSE 流式请求逻辑
│   │   ├── services/
│   │   │   └── api.ts              # 前端 API 请求封装
│   │   ├── types/
│   │   │   └── index.ts            # TypeScript 类型定义
│   │   ├── App.tsx                 # 根组件
│   │   └── main.tsx                # React 入口
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
└── README.md
```

## 3. 核心数据结构设计 (Pydantic Models)

后端需基于提供的 JSON Schema 定义严格的 Pydantic 模型，以确保数据流转的类型安全。请在 `backend/app/models/schemas.py` 中实现：

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class PeriodInfo(BaseModel):
    fiscal_year: int
    fiscal_period: str
    date_label: str

class FinancialMetric(BaseModel):
    name: str
    value: str
    normalized_value: float
    unit: str
    period_label: str

class ChunkData(BaseModel):
    chunk_id: str
    chunk_index: int
    section_id: str
    section_title: str
    page_start: int
    page_end: int
    chunk_type: str
    content: str
    content_brief: Optional[str] = None
    keywords: List[str] = []
    period: Optional[PeriodInfo] = None
    financial_metrics: List[FinancialMetric] = []
    # 其他字段根据 Schema 补充...

class DocumentSchema(BaseModel):
    document: Dict[str, Any]
    sections: List[Dict[str, Any]]
    chunks: List[ChunkData]
```

## 4. 核心模块实现指南

### 4.1 索引管道 (Indexing Pipeline)

**目标**：解析 JSON，调用 LLM 生成摘要，使用 BGE-M3 提取 Dense 和 Sparse 向量，并存入 Qdrant。

1.  **Qdrant 集合初始化** (`backend/app/utils/qdrant_client.py`)：
    使用 `qdrant-client` 的本地模式初始化集合，配置 `dense` 和 `sparse` 两个命名向量。

    ```python
    from qdrant_client import QdrantClient, models
    
    client = QdrantClient(path="./data/qdrant_storage")
    client.create_collection(
        collection_name="financial_reports",
        vectors_config={
            "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams()
        }
    )
    ```

2.  **块级元数据增强** (`backend/app/services/indexer.py`)：
    由于上游预处理已在 JSON Schema 中提供了丰富的元数据（如 `section_title`、`section_summary`、`content_brief`、`period` 等），系统**无需再调用 LLM 生成摘要**。
    直接利用 Schema 中已有的字段进行字符串拼接，形成高信息密度的 `augmented_text`。
    
    ```python
    augmented_texts = []
    for chunk in chunks:
        # 提取公司名、财报期间、章节标题和块级简短摘要
        company = document_metadata.get("company_name", "")
        period_label = chunk.period.date_label if chunk.period else ""
        
        # 拼接格式：[公司名] [期间] - [章节标题] \n [块级摘要] \n\n [正文]
        header = f"{company} {period_label} - {chunk.section_title}"
        brief = chunk.content_brief if chunk.content_brief else ""
        
        augmented_text = f"{header}\n{brief}\n\n{chunk.content}".strip()
        augmented_texts.append(augmented_text)
    ```

3.  **BGE-M3 向量提取与存储** (`backend/app/services/indexer.py`)：
    使用 `FlagEmbedding` 提取向量。注意：此处**不存储** ColBERT 向量。

    ```python
    from FlagEmbedding import BGEM3FlagModel
    
    model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
    
    # 提取 Dense 和 Sparse
    embeddings = model.encode(augmented_texts, return_dense=True, return_sparse=True)
    dense_vecs = embeddings['dense_vecs']
    lexical_weights = embeddings['lexical_weights'] # List of dicts {token_id: weight}
    
    # 构造 Qdrant PointStruct 并插入
    points = []
    for i, chunk in enumerate(chunks):
        # 将 lexical_weights 转换为 Qdrant SparseVector 格式
        indices = list(lexical_weights[i].keys())
        values = list(lexical_weights[i].values())
        
        points.append(models.PointStruct(
            id=chunk.chunk_id, # 需转换为 UUID 或整数
            vector={
                "dense": dense_vecs[i].tolist(),
                "sparse": models.SparseVector(indices=indices, values=values)
            },
            payload=chunk.model_dump() # 存储完整 Chunk 数据
        ))
    client.upsert(collection_name="financial_reports", points=points)
    ```

### 4.2 检索管道 (Retrieval Pipeline)

**目标**：查询重写，Qdrant 混合检索，页面级块绑定。

1.  **查询重写** (`backend/app/services/retriever.py`)：调用智谱 API，将用户 Query 转换为标准化检索词。
2.  **混合检索 (Hybrid Search)** (`backend/app/services/retriever.py`)：
    使用 Qdrant 的 Query API 和 Reciprocal Rank Fusion (RRF) 进行多路召回。

    ```python
    # 1. 对重写后的 Query 提取向量
    query_emb = model.encode([rewritten_query], return_dense=True, return_sparse=True)
    q_dense = query_emb['dense_vecs'][0].tolist()
    q_sparse_dict = query_emb['lexical_weights'][0]
    
    # 2. Qdrant RRF 混合检索
    results = client.query_points(
        collection_name="financial_reports",
        prefetch=[
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(q_sparse_dict.keys()), 
                    values=list(q_sparse_dict.values())
                ),
                using="sparse",
                limit=50
            ),
            models.Prefetch(
                query=q_dense,
                using="dense",
                limit=50
            )
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=80
    )
    ```

3.  **页面级块绑定 (Chunk Bundling)** (`backend/app/services/retriever.py`)：
    提取 `results` 中的 `payload`，按 `page_start` 排序。检测连续页码，将连续的 Chunk 拼接为一个复合上下文块 (Bundled Context)。

### 4.3 重排序与生成管道 (Re-ranking & Generation Pipeline)

**目标**：ColBERT 实时计算，Cross-Encoder 深度打分，LLM 最终生成。

1.  **一级重排序 (ColBERT MaxSim)** (`backend/app/services/reranker.py`)：
    对上一步得到的 50-80 个 Bundled Contexts 实时计算 ColBERT 向量。

    ```python
    # 提取 Query 的 ColBERT 向量
    q_colbert = model.encode([rewritten_query], return_colbert_vecs=True)['colbert_vecs'][0]
    
    # 提取 Contexts 的 ColBERT 向量并打分
    ctx_colberts = model.encode(contexts, return_colbert_vecs=True)['colbert_vecs']
    
    scores = []
    for ctx_colbert in ctx_colberts:
        score = model.colbert_score(q_colbert, ctx_colbert)
        scores.append(score)
    
    # 根据 scores 筛选 Top-10
    ```

2.  **二级重排序 (Cross-Encoder)** (`backend/app/services/reranker.py`)：
    使用 `bge-reranker-v2-gemma` 对 Top-10 进行极限精排。

    ```python
    from FlagEmbedding import FlagLLMReranker
    reranker = FlagLLMReranker('BAAI/bge-reranker-v2-gemma', use_fp16=True)
    
    pairs = [[rewritten_query, ctx] for ctx in top_10_contexts]
    rerank_scores = reranker.compute_score(pairs)
    
    # 筛选 Top-3 作为最终上下文
    ```

3.  **答案生成** (`backend/app/services/generator.py`)：
    将 Top-3 上下文拼接，构建 Prompt，调用智谱 API 生成最终回答。Prompt 需严格约束模型仅使用提供的上下文，并要求标注来源页码（如 `[Page 25]`）。

## 5. 核心 Prompt 模板设计

在 `backend/app/core/prompts.py` 中集中管理 Prompt：

```python
QUERY_REWRITE_PROMPT = """
你是一个专业的金融分析师。请将用户的自然语言查询重写为适合向量检索的标准化查询。
提取核心实体（公司、时间、指标），并补充相关的金融同义词。

用户查询: {user_query}
重写后的查询:
"""

ANSWER_GENERATION_PROMPT = """
你是一个严谨的财务报表问答助手。请严格基于以下提供的上下文回答用户的问题。

【约束条件】
1. 强制仅基于提供的上下文回答问题，禁止使用内部知识。
2. 如果上下文中没有足够的信息回答问题，请明确回答“根据提供的文档，无法回答该问题”。
3. 若回答涉及具体数值或事实，必须在句子末尾的括号内标注来源页码，格式为：[Page X]。
4. 保持客观、专业的语气。

【上下文】
{context}

【用户问题】
{user_query}

【回答】
"""
```

## 6. API 接口设计 (FastAPI)

后端需提供以下核心 RESTful API：

*   `POST /api/v1/documents`：接收 JSON 文件上传，触发异步的 Indexing Pipeline。
*   `GET /api/v1/documents`：获取已索引的文档列表。
*   `POST /api/v1/chat`：接收用户 Query，执行 Retrieval -> Reranking -> Generation 完整链路，支持 Server-Sent Events (SSE) 流式输出。

## 7. 前端交互设计 (React)

前端界面应包含两个主要区域：

1.  **文档管理区 (侧边栏)**：支持上传符合 Schema 的 JSON 文件，显示处理状态。
2.  **问答交互区 (主区域)**：
    *   类似 ChatGPT 的对话界面。
    *   支持流式打字机效果显示回答。
    *   **关键特性**：当回答中包含引用页码（如 `[Page 25]`）时，前端应将其渲染为可点击的 Badge。点击后，在侧边栏或弹窗中展示该页对应的原始 Chunk 内容（包括表格数据），以增强可解释性。

## 8. 部署与运行建议

*   **环境隔离**：建议使用 `uv` 或 `poetry` 管理 Python 依赖。
*   **模型下载**：在首次启动前，编写脚本预先从 Hugging Face 下载 `bge-m3` 和 `bge-reranker-v2-gemma` 模型至本地缓存。
*   **硬件要求**：由于包含本地 LLM Reranker 和 BGE-M3，建议在配备至少 16GB 显存的 GPU 环境下运行（如 RTX 4080/4090 或 A10G）。

## References

[1] Qdrant Documentation: Hybrid Queries. https://qdrant.tech/documentation/search/hybrid-queries/
[2] BAAI/bge-m3 Model Card. https://huggingface.co/BAAI/bge-m3
[3] BAAI/bge-reranker-v2-gemma Model Card. https://huggingface.co/BAAI/bge-reranker-v2-gemma
[4] ZhipuAI Python SDK. https://github.com/MetaGLM/zhipuai-sdk-python-v4

---
*本文档由 Manus AI 自动生成，专为 Claude Code 工程实现提供架构指导。*
