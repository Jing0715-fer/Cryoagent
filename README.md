# CryoAgent Pro — 蛋白质结构智能分析平台

> 基于 AI 的 Cryo-EM 文献与蛋白质结构智能分析系统 · 由 Flask + Python 完整重构为 Next.js 16 + TypeScript

[![Tech](https://img.shields.io/badge/Next.js-16-black)](https://nextjs.org) [![Lang](https://img.shields.io/badge/TypeScript-5-blue)]() [![DB](https://img.shields.io/badge/Prisma-SQLite-teal)]() [![UI](https://img.shields.io/badge/shadcn%2Fui-New%20York-orange)]()

## 重构说明

本项目是 [Cryoagent](https://github.com/Jing0715-fer/Cryoagent) 的**完整重构版本**：保留全部核心功能，架构从 Flask + Python + 原生 JS 升级为现代全栈 TypeScript 技术栈，并新增多项功能。

| 维度 | 原版 (Flask) | 重构版 (Next.js Pro) |
|---|---|---|
| 框架 | Flask + Jinja2 多页 | Next.js 16 App Router 单页应用 |
| 语言 | Python 3 | TypeScript 5 (严格模式) |
| 数据库 | SQLAlchemy + LanceDB | Prisma + SQLite (14 模型) |
| 检索 | BM25 (rank_bm25) + 句向量 | 自研 TS BM25 + TF-IDF 向量 + RRF 融合 |
| AI | Anthropic Claude API | z-ai-web-dev-sdk (SSE 流式) |
| 比对 | BioPython pairwise2 | 自研 Gotoh 仿射间隙 NW/SW + BLOSUM45/62 + PAM250 |
| 前端 | 原生 HTML/JS + ECharts | React 19 + shadcn/ui + Recharts + 自研 SVG 力导图 |
| 3D | PyMOL (需安装) | 3Dmol.js 内嵌 (零安装) |
| 主题 | 固定 | 亮/暗/跟随系统 (next-themes) |

## 功能特性

### 🎯 核心功能 (保留自原版)

- **智能问答 Agent** — RAG 双模式: RAG 流式问答 (SSE, 引用来源可溯源) + Agent 模式 (11 个工具自主调用多步推理)
- **文献管理** — PDF/TXT/MD 上传 → 解析分块 (章节识别) → 混合索引 → 自动提取关联 PDB 结构
- **结构浏览器** — RCSB 实时检索 + 本地缓存, PDB/EMDB/UniProt/AlphaFold 元数据聚合
- **3D 结构查看器** — 3Dmol.js 内嵌渲染 (cartoon/stick/sphere/line × spectrum/residue/chain 配色)
- **知识图谱** — 结构-文献-蛋白质关联网络, 全图/邻域/最短路径三种查询模式
- **序列比对** — Needleman-Wunsch / Smith-Waterman, BLOSUM62/45 + PAM250, 逐字符着色比对视图
- **Skills 系统** — 14 个预设专家技能 (结构比较/文献综述/序列分析/方法指南/蛋白质设计/靶点分析/突变分析等)
- **RAG 评估** — Ground Truth 标注, Precision/Recall/F1/MRR/命中率, 搜索监控统计
- **用户认证** — 注册/登录 (scrypt 哈希 + HMAC 签名 Cookie 会话)

### ✨ 新增功能

- **仪表盘** — 平台统计总览: 活跃趋势图、方法分布、热门结构、检索健康度
- **序列理化分析** — 蛋白质: 分子量/等电点/GRAVY/不稳定指数/Chou-Fasman 二级结构倾向/疏水性剖面; 核酸: GC 含量/Tm/ORF 发现/密码子统计/翻译
- **命令面板** — ⌘K 全局快速跳转
- **文献阅读笔记** — 每篇文献独立笔记 CRUD
- **接口文档中心** — 43 个端点在线文档 + 14 个可在线调试
- **暗色模式** — 完整的亮/暗主题适配
- **API 在线调试** — 文档页一键试运行

## Agent 工具集 (11 个)

`search_literature` · `search_structures` · `get_structure_details` · `run_sequence_alignment` · `fetch_uniprot` · `find_similar_sequences` · `get_kg_neighbors` · `compare_structures` · `analyze_resolution` · `analyze_sequence` · `get_publication_info`

## 技术栈

- **框架**: Next.js 16 (App Router) + React 19
- **语言**: TypeScript 5 (strict)
- **UI**: Tailwind CSS 4 + shadcn/ui (New York) + Lucide + Framer Motion
- **状态**: Zustand (客户端) 
- **数据库**: Prisma ORM + SQLite
- **AI**: z-ai-web-dev-sdk (服务端调用, SSE 流式推送)
- **图表**: Recharts + 自研 SVG 力导向图
- **3D**: 3Dmol.js (CDN)
- **外部数据**: RCSB PDB API / UniProt REST / AlphaFold DB / EMDB (PDBe API)

## 快速开始

```bash
# 安装依赖
bun install

# 初始化数据库
bun run db:push

# 启动开发服务器
bun run dev        # http://localhost:3000

# 代码检查
bun run lint
```

首次访问会自动注入演示数据 (6 篇经典 Cryo-EM 文献 + 14 技能 + 关联结构)。

## 项目结构

```
├── prisma/schema.prisma          # 14 数据模型
├── src/
│   ├── app/
│   │   ├── page.tsx              # 单页应用入口 (视图切换)
│   │   └── api/                  # 20 组 REST API 路由
│   │       ├── auth/             # 认证
│   │       ├── literature/       # 文献 (上传/解析/分块)
│   │       ├── search/           # 混合检索
│   │       ├── qa/               # 问答 (ask SSE / agent / history)
│   │       ├── structure/        # 结构 (详情/3D 坐标)
│   │       ├── kg/               # 知识图谱
│   │       ├── alignment/        # 序列比对
│   │       ├── sequence/         # 理化分析
│   │       ├── skills/           # 技能
│   │       ├── evaluation/       # RAG 评估
│   │       └── ...
│   ├── components/
│   │   ├── app-shell.tsx         # 应用外壳 (导航/命令面板)
│   │   ├── force-graph.tsx       # SVG 力导向图
│   │   ├── markdown-view.tsx     # Markdown 渲染
│   │   └── views/                # 13 个视图组件
│   └── lib/
│       ├── agent.ts              # Agent 工具注册与调用循环
│       ├── search-engine.ts      # BM25 + TF-IDF + RRF
│       ├── alignment.ts          # Gotoh NW/SW + 替换矩阵
│       ├── protein-analysis.ts   # 序列理化性质
│       ├── bio-apis.ts           # RCSB/UniProt/AlphaFold 客户端
│       ├── llm.ts                # LLM 服务 (流式/重试)
│       ├── rag.ts                # RAG 检索服务
│       ├── skills.ts             # 14 预设技能
│       ├── document-parser.ts    # PDF/TXT 解析与分块
│       └── auth.ts               # 会话认证
└── uploads/                      # 上传文件存储
```

## API 概览

| 分组 | 端点 | 说明 |
|---|---|---|
| 认证 | `POST /api/auth` | register / login / logout |
| 文献 | `GET/POST /api/literature` | 列表 / 上传解析 |
| 文献 | `GET/PATCH/DELETE /api/literature/[id]` | 详情 / 更新 / 删除 |
| 检索 | `POST /api/search` | bm25 / vector / hybrid |
| 问答 | `POST /api/qa/ask` | RAG 流式 (SSE) |
| 问答 | `POST /api/qa/agent` | Agent 工具调用 |
| 结构 | `GET /api/structure/[id]` | 详情 (RCSB + 缓存) |
| 结构 | `GET /api/structure/[id]/pdb` | 3D 坐标 |
| 图谱 | `GET /api/kg` · `GET /api/kg/neighborhood/[id]` | 全图 / 邻域 |
| 比对 | `POST /api/alignment` | NW/SW 比对 |
| 序列 | `POST /api/sequence/analyze` | 理化性质 |
| 技能 | `GET /api/skills` | 技能列表 |
| 评估 | `POST /api/evaluation` | 检索质量评估 |
| 统计 | `GET /api/stats` | 仪表盘数据 |

完整交互式文档见应用内「接口文档」页面。

## License

MIT
