# Financial RAG - 财报问答系统

基于 RAG 的财务报表智能问答系统，支持对结构化财报数据进行索引、检索和问答。

## 项目结构

```
.
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── api/           # API 路由
│   │   ├── core/          # 配置和 Prompts
│   │   ├── models/         # Pydantic 模型
│   │   ├── services/       # 核心业务逻辑
│   │   └── utils/          # 工具函数
│   ├── data/              # 数据存储
│   └── requirements.txt
├── frontend/              # React 前端
│   └── src/
│       ├── components/    # UI 组件
│       ├── hooks/         # React Hooks
│       ├── services/      # API 服务
│       └── types/         # TypeScript 类型
├── prd.md                 # 产品需求文档
└── coding_spec.md         # 技术规格文档
```

## 快速开始

### 后端

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 环境变量

在 `backend/` 目录下创建 `.env` 文件：

```
ZHIPU_API_KEY=your_api_key
QDRANT_PATH=./data/qdrant_storage
```

## API 文档

启动后端后访问 http://localhost:8000/docs 查看 Swagger UI
