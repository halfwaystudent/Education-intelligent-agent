# 教育行业智能答疑助手 MVP

本项目是本地/单机版高校课程智能答疑助手地基，当前重点完成：课程管理、资料导入、Chroma 向量索引、SQLite 元数据、带引用的 RAG 问答接口。

## 整体架构：三层分离

系统采用"检索→展示→推理"三层分离的设计：

**1. Embedding 检索层（本地，不动）**
- 结构化题干、材料、答案和解析生成主 embedding 文本；图片/公式题额外追加 `visual_ocr` 文本
- 原始 `IMAGE_xxx:path` 路径在 embedding 前会被清洗为 `[图片/公式]`，不会把本地路径写入向量
- 本地 BGE-M3 使用 2048 token 上限，并对材料、题干、答案、选项和解析分别限长

**2. 展示层（本地 PNG）**
- 仅对包含图片或公式的题目生成 PNG（`data/question_rendered/images/`），避免无意义 OCR
- 对应 chunk metadata 保存 `question_image_path` 和 `question_image_url`，前端可展示题目图片

**3. 推理层（多模态 LLM，按需调用）**
- 学生上传题目或提问时，把整题 PNG 发给 GPT-4o/Claude Vision
- 模型直接从图片中提取题干、选项、公式（自动转 LaTeX），生成解析
- 不依赖本地公式 OCR（如 pix2tex），避免高考公式识别不稳定

## 环境

```powershell
conda activate agent
pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
```

如使用 OpenAI 或兼容 OpenAI API 的模型，在 `.env` 中填写：

```env
OPENAI_API_KEY=你的 key
OPENAI_BASE_URL=https://api.openai.com/v1
CHAT_MODEL=gpt-4o-mini
```

Embedding 默认使用本地 `sentence-transformers` 模型 `BAAI/bge-m3`，不会因为配置了 `OPENAI_API_KEY` 而自动切到 OpenAI embedding：

```env
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=BAAI/bge-m3
CHROMA_COLLECTION=course_chunks_bge_m3
LOCAL_EMBEDDING_MAX_SEQ_LENGTH=2048
EMBEDDING_MAX_CHARS=6000
RETRIEVAL_MIN_SCORE=0.50
```

如果确实要使用 OpenAI 或兼容 OpenAI API 的 embedding，再显式配置：

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
```

切换 embedding 模型后需要重建 Chroma 索引。推荐更换 `CHROMA_COLLECTION` 名称，或清空旧 collection 后重新导入课程资料。

数学试题默认启用整题视觉 OCR embedding：系统会把题目 HTML 渲染为 PNG，再用本地 `rapidocr` 识别为文本写入向量库，同时把 PNG 路径写入 chunk metadata 供前端展示。首次导入会比纯文本慢，后续会命中缓存。

```env
QUESTION_RENDER_OCR_ENABLED=true
QUESTION_RENDER_OCR_IMAGE_ONLY=true
QUESTION_RENDER_DPI_SCALE=2
QUESTION_RENDER_WIDTH=960
QUESTION_RENDER_DIR=data/question_rendered
```

如果 Playwright 浏览器缺失，执行 `python -m playwright install chromium`。如果整题 OCR 失败或识别文本过短，系统会自动回退到原始解析文本，不会中断导入。

不配置可用聊天模型时，聊天回答会降级为基于检索原文的保守摘要，不会编造课程内容。

## 启动

```powershell
conda activate agent
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

接口文档：`http://127.0.0.1:8000/docs`

前端演示页：`http://127.0.0.1:8000/`

## API

- `POST /api/courses` 创建课程
- `GET /api/courses` 查看课程
- `POST /api/upload` 上传文件到指定学科知识库，由 `document_agent` 完成加载、AI/规则优化、切割、向量化和入库。`form-data` 可传 `subject=语文/数学/英语`，也可直接传 `collection_name`
- `POST /api/papers/analyze` 上传并解析语文、数学、英语试卷。`form-data` 传 `subject=语文/数学/英语`、`file=docx/pdf`、可选 `question`，返回 `report_markdown` 和结构化 `questions`
- `POST /api/courses/{course_id}/documents` 上传并索引 `PDF`、`DOCX`、`TXT`、`Markdown`
- `POST /api/courses/{course_id}/reindex` 重建课程文档索引
- `POST /api/chat` 知识库问答，必须传 `subject`、`collection_name` 或有效的 `course_id`，响应会返回经过阈值过滤和材料去重的 `retrieved_chunks`
- `GET /api/chat/{session_id}/messages` 查看聊天记录
- `GET /api/documents/{document_id}/chunks` 查看切分结果

## 扫描版 PDF OCR

系统会先尝试直接提取 PDF 文本；如果判断为扫描/复印件图片型 PDF，会自动用本地 `rapidocr` 做 OCR，再进入切分和索引流程。

注意事项：

- OCR 不调用云服务，默认本地执行。
- 扫描教材页数较多，首次导入会比较慢。
- 第一版只做文字识别，不做数学公式 LaTeX 结构化识别，公式可能变成近似文本。
- OCR 需要 `pdftoppm` 渲染 PDF 页面；当前 Codex 运行环境已带该工具，如果本机命令行缺失，需要安装 Poppler 并加入 `PATH`。
- 如果提示缺少 OCR 依赖，执行：`conda activate agent && pip install -r requirements.txt`。

## 本地目录导入

```powershell
conda activate agent
python scripts/ingest_local.py --course "机器学习" --path "D:\课程资料"
```

## 当前边界

- 知识库资料先为空，等课程资料确定后导入。
- MVP 不做拍照搜题、数学公式 OCR、自动判卷。
- 公式在 embedding 中保留占位符，不影响检索效果；需要"看懂公式"的场景走多模态 LLM。
- 题目解析只预留文本题链路，当前按 `problem_solving` 路由返回结构化解析。
- 回答必须返回 `citations`、`route`、`confidence`，无资料支撑时明确说明资料不足。

## 数学公式与题目 HTML 展示

数学 DOCX 中的 WMF/EMF 公式会在构建 chunk 时缓存转换为 PNG，输出目录为 `data/image_ocr_rendered/`。应用通过 `/media/formulas/...` 提供只读访问，`display_html` 使用受控的 `<img>` 标签引用公式图片。

每个数学 chunk 同时保留：

- `image_paths`：DOCX 提取出的原始图片或公式路径
- `display_image_paths`：转换后的浏览器兼容 PNG 路径
- `display_image_urls`：前端可直接访问的公式 URL
- `question_image_path` / `question_image_url`：整题渲染图路径与 URL，供后续多模态模型使用

聊天页面会对白名单 HTML 进行清洗后展示题干、选项、答案和解析。已有数学文档需要重新索引，旧 chunk 才会获得这些字段。

## Vue 前端

新版前端源码位于 `frontend/`，包含智能答疑、试卷分析、知识库管理和向量检索诊断四个模块。

开发模式：

```powershell
cd frontend
pnpm install
pnpm dev
```

Vite 默认运行在 `http://127.0.0.1:5173`，并将 `/api`、`/media`、`/reports` 代理到 `http://127.0.0.1:8000`。如果后端运行在其他端口，可设置：

```env
VITE_API_BASE_URL=http://127.0.0.1:你的端口
```

生产构建：

```powershell
cd frontend
pnpm build
cd ..
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

FastAPI 会自动托管 `frontend/dist`，访问 `/chat`、`/papers`、`/knowledge` 均会回退到 Vue SPA。

新增接口：

- `POST /api/chat/stream`：SSE 流式答疑
- `GET /api/chat/sessions`：会话列表
- `PATCH /api/chat/sessions/{session_id}`：重命名会话
- `DELETE /api/chat/sessions/{session_id}`：删除会话
- `GET /api/collections`：三个学科知识库汇总
- `GET /api/collections/{collection_name}/documents`：知识库文档列表
- `POST /api/collections/{collection_name}/search`：只读向量检索诊断

数据库在应用启动时执行版本化迁移，为历史会话补充学科、标题、更新时间和置信度字段。


## 清理并重建三科学科索引

索引重建脚本会自动修复项目移动后失效的上传文件路径，并支持中断后继续执行：

```powershell
conda activate agent
python scripts/rebuild_subject_indexes.py --subjects 语文 数学 英语
```

默认跳过已经是 `indexed` 的文档。需要强制全部重建时使用：

```powershell
python scripts/rebuild_subject_indexes.py --subjects 语文 数学 英语 --force
```

检索默认先取扩大后的候选集，再执行：最低相似度 `0.50`、过滤 `fallback_split/unmatched_answer`、每个材料最多一条、每个文档最多两条，并针对英语题型做轻量重排。

启动位置不再影响数据目录：配置会固定从项目根目录读取 .env，并解析到根目录下的 data/app.db、data/chroma 和 data/uploads。
