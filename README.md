# CryoAgent - 蛋白质结构智能分析平台

基于 AI 的 Cryo-EM（冷冻电子显微镜）文献与蛋白质结构智能分析系统。

## 功能特性

- **智能问答 Agent**：基于大语言模型的智能问答系统，支持文献理解和结构分析
- **文献管理**：PDF 文献上传、解析、索引和检索，支持 RAG 混合搜索
- **结构浏览器**：PDB、EMDB、AlphaFold 蛋白质结构数据可视化
- **蛋白质知识图谱**：结构-功能-文献关联知识图谱
- **序列比对**：内置序列比对工具
- **飞书集成**：支持飞书文档同步和管理

## 技术栈

- **后端**：Flask + Python
- **AI/ML**：Anthropic Claude API、Sentence Transformers（本地 Embedding）
- **数据库**：LanceDB（向量数据库）、SQLite
- **搜索**：BM25 全文搜索 + 向量检索混合
- **前端**：HTML/CSS/JavaScript（原生 + ECharts）

## 项目结构

```
Cryoagent/
├── app.py                      # Flask 应用入口
├── config.py                   # 配置文件
├── requirements.txt            # Python 依赖
├── run.sh                      # 启动脚本
├── ai_config.json              # AI 模型配置
├── core/                       # 核心业务模块
│   ├── agent_core.py           # Agent 核心
│   ├── agent_tools.py          # Agent 工具
│   ├── literature_agent.py     # 文献处理 Agent
│   ├── qa_agent.py             # 问答 Agent
│   ├── literature_db.py        # 文献数据库
│   ├── literature_index.py     # 文献索引
│   ├── structure_manager.py    # 结构管理
│   ├── structure_database.py   # 结构数据库
│   ├── structure_knowledge_graph.py  # 知识图谱
│   ├── lancedb_rag/           # LanceDB RAG 实现
│   │   ├── rag.py
│   │   ├── hybrid.py           # 混合搜索
│   │   ├── bm25.py
│   │   ├── embedding.py
│   │   └── reranker.py
│   └── ...
├── routes/                     # API 路由
│   ├── literature.py
│   ├── structure.py
│   ├── qa.py
│   ├── qa_agent.py
│   ├── upload.py
│   ├── alignment.py
│   ├── kg.py                   # 知识图谱
│   └── ...
├── services/                   # 服务层
│   ├── feishu_document.py      # 飞书文档服务
│   └── wrapper.py
├── templates/                  # 前端模板
├── static/                     # 静态资源
├── data/                       # 数据目录
│   └── lancedb/               # LanceDB 数据库
├── literature/                 # 文献存储
├── structure_cache/           # 结构缓存
└── uploads/                    # 上传文件
```

## 安装

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows

# 安装依赖
pip install -r requirements.txt
```

## 配置

1. 复制并配置 `ai_config.json`：

```json
{
  "anthropic_api_key": "your-api-key",
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 4096
}
```

2. 或设置环境变量：

```bash
export ANTHROPIC_API_KEY="your-api-key"
```

## 运行

### 开发模式

```bash
python app.py
# 访问 http://localhost:5000
```

### 使用启动脚本

```bash
./run.sh
```

## API 接口

### 文献管理
- `GET /api/literature` - 获取文献列表
- `GET /api/literature/<id>` - 获取文献详情
- `POST /api/upload` - 上传 PDF 文献
- `DELETE /api/literature/<id>` - 删除文献

### 结构数据
- `GET /api/structure/<id>` - 获取结构详情
- `POST /api/structure/search` - 搜索结构

### 智能问答
- `POST /api/qa/ask` - 提问（传统方式）
- `POST /api/qa/agent` - Agent 智能问答

### 知识图谱
- `GET /api/kg/search` - 搜索知识图谱
- `GET /api/kg/structure/<id>` - 获取结构关联信息

## License

MIT
