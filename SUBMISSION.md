# 提交说明

## 评审入口

- Fork：https://github.com/wangzhichuan123/AI-Engineer-Quiz （公开，可匿名读取）
- 开发分支：`feat/asset-search-export`
- 起点：`3aa137ccde6f981981582f6f71b81448c72a9dab`，保留所有上游历史。
- 最终 SHA 见交付回复；克隆分支后可执行 `git rev-parse HEAD` 核对。文档不嵌入自身 commit SHA，避免自引用。
- 实际开发按后端、页面、浏览器验证修正和交付文档分次提交；未 squash、amend、rebase。

## 安装与运行

需要 Python 3.10+（实测 3.11.7）、Node 18+（仅前端自动化测试需要；页面无需构建），SQLite 带 FTS5。
在仓库根目录执行：

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell 改用：.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-test.txt -e '.[dev]'
```

`requirements-test.txt` 固定本次验证使用的依赖版本；未引入新运行时组件。

Linux/macOS：

```bash
export KEEPSTACK_AI_ENABLED=false
export KEEPSTACK_OCR_ENABLED=false
export KEEPSTACK_DATA_DIR=data/search-demo
python -m keepstack.search_demo
python -m keepstack
```

Windows PowerShell：

```powershell
$env:KEEPSTACK_AI_ENABLED='false'
$env:KEEPSTACK_OCR_ENABLED='false'
$env:KEEPSTACK_DATA_DIR='data/search-demo'
python -m keepstack.search_demo
python -m keepstack
```

打开 http://localhost:8000，使用题目默认账号 `admin` / `admin` 登录。
也可以使用原有 `python -m keepstack seed` 生成 24 个素材，但请使用另一个空目录。
生成器会拒绝非空素材库，不会覆盖已有素材。重新运行服务无需重新生成数据。

## 操作与数据预期

`keepstack/search_demo.py` 创建 73 个素材（72 个 active）、2 个集合及实际可预览/下载的合成文件；无需外部数据。
其中 65 个基础匹配项，另有排除标签、缺少标签、其他集合、deleted、图片类型、其他关键词、近似标签及特殊标签控制项。
每 5 项共享创建时间，确保分页边界穿过相同时间；UUID 每次生成不同，内容、结果数和排序关系可复现。

1. Library 输入 `harbor`，Collection 选择 `Harbor campaign`。
2. Include all tags 分别添加 `approved`、`campaign`；Exclude any tags 添加 `internal`。
3. Media type 选择 `Document`，Sort 选择 `Oldest`：应有 **66** 条，24 条/页，共 3 页。
4. 第 1 页标题 `Harbor asset 000` 至 `023`，第 2 页 `024` 至 `047`；第 3 页 `048` 至 `064`，以及 `072`。
5. 从任意页点击 Export all matches (CSV)，应导出 66 行数据，不含表头计数。清除类型限制应为 67 条（多 1 张图片）。
6. 标签按钮可逐个移除，Clear filters 清除全部筛选；排序保留。修改条件/排序回到第一页。
7. 点开素材可编辑标题、描述、新增或移除标签；下一次列表查询与导出反映修改。

包含/排除使用完整标签名（trim + lower，与新增标签一致），每次添加一个名称；逗号、空格、引号属于名称本身，绝不当作分隔符。
重复包含项无影响；包含与排除重叠返回空结果。侧栏数字明确标为全库 active 素材统计，不是当前匹配数。
空白关键词不限制；沿用原 FTS 字段、`porter unicode61` 和原前缀查询转换；只有标点的非空输入没有可检索词，返回 0 条。

## API 与 CSV 格式

列表：`GET /api/assets`。导出：`GET /api/assets/export.csv`（注册在 UUID 路由之前）。
两者均沿用 `Authorization: Bearer <登录 token>` 鉴权，仅检索 active 素材。
共享参数：`q`、`collection_id`、`media_type`、可重复的 `include_tags` / `exclude_tags`、`sort=newest|oldest`。
兼容原单个 `tag`（附加到包含条件），以及 `name` / `largest` 排序；页面仅提供题目要求的时间排序。
`status` 只允许 active，`mode` 只允许 keyword；语义搜索入口隐藏，内部语义搜索功能保留供上游代码使用。

例如：

```text
/api/assets?q=harbor&collection_id=1&include_tags=approved&include_tags=campaign&exclude_tags=internal&media_type=document&sort=oldest&limit=24&offset=24
/api/assets/export.csv?q=harbor&collection_id=1&include_tags=approved&include_tags=campaign&exclude_tags=internal&media_type=document&sort=oldest
```

列表 `limit` 为 1–200，`offset` 为非负 SQLite 64 位整数，集合 ID 为正 SQLite 64 位整数；非法参数返回 422。
超出末页返回空 items 和正确 total；页面在编辑导致末页消失时自动回第一页。
导出忽略分页参数，输出全部匹配结果；0 条仍有表头。
CSV 为 **UTF-8 BOM**，使用 Python `csv` 标准库、CRLF 行终止符；中文、逗号、双引号、字段内换行均可往返解析。
列为 `uuid,title,description,filename,media_type,tags,created_at`；`tags` 是按名称排序的 JSON 数组，空值输出空字段。
原始字段内容保留，不做电子表格公式转义；如导入不可信素材元数据到电子表格，应按文本导入。

## 自动化验证及实测

```bash
python -m pytest -q
node --test tests/test_web.cjs
node --check web/app.js
git diff --check
```

2026-11-24，Windows、Python 3.11.7、Node 20.19.0，关闭 AI/OCR，本地实测：

- Python：**44 passed, 2 skipped**，约 86 秒。跳过项为未安装的本地 CLIP 模型和 OCR；3 条上游/依赖弃用警告不影响结果。
- Node：**6 passed**，无失败。覆盖真正 SPA 代码的防抖间隙旧响应、乱序响应/失败、重置页码、完整标签名、鉴权下载与失败提示、登录默认 POST。
- HTTP 测试使用真实登录 token、FTS5、SQLite 和上述数据生成器；临时目录隔离，不触碰实际素材库。
- 覆盖条件交集、全包含/任一排除、重叠/重复/大小写/近似与特殊标签、集合和类型、双向多页及相同时间、列表/导出 UUID 顺序完全一致、分页不限制导出、CSV 往返及空表头、非法参数/未登录、标题/描述/标签修改后检索与导出。
- 实际浏览器：默认账号登录、组合条件得到 66 条、翻到第 2 页、下载 CSV 后用 `csv.DictReader` 复核 **66 行、66 个唯一 UUID、首尾为 000/072**；时间排序切换回第 1 页。窄屏也可使用素材类型选择。
- `node --check` 和 `git diff --check` 通过。

`.github/workflows/ci.yml` 在 main、开发分支 push 与 PR 上执行 Python 3.10/3.12、前端测试；CI 保留原有 Tesseract 安装以验证可选 OCR。
本地 Windows 沙箱不能创建 asyncio 的 socketpair，HTTP 测试以允许本地套接字的执行方式运行；这属于执行环境约束，无测试绕过。

## 主要取舍、限制和未完成项

- 保留 FastAPI / SQLite / 原生 JavaScript。列表与导出共用 SQL 构造器；EXISTS 避免标签或集合 JOIN 放大行数，也修复原参数顺序绑定错误。
- 时间排序增加同向唯一 ID 作为次排序，有关键词也遵守该排序。SQL 数据值全部绑定，排序只能来自固定映射。
- 前端使用 AbortController 加请求版本号，输入变化时立即使旧请求失效（包括 250ms 防抖等待期）；明确展示加载、空结果、失败及重试状态。
- 修改接口已有 FTS 重建逻辑，经 HTTP 回归验证有效；修复原前端 JSON 请求默认 GET 导致登录/标签新增失败的问题，并使标签编辑刷新列表。
- 使用同步内存 CSV：实现简单、失败可在发送前返回；代价是导出内存随 CSV 大小增长，每个资产读取一次标签。未实现流式/异步大批量导出；适用本题规模。
- OFFSET 深页性能与数据量相关；没有跨请求快照，数据改变时可能移动页边界，符合题目不变数据验收约定。
- 自动化前端测试是 Node VM 与最小 DOM/网络替身，验证请求生命周期；真实布局、原生下载通过本次浏览器实测，尚无完整自动化浏览器 E2E 套件。
- 范围外：上游单文件 Download 链接未附带 Bearer、公开缩略图/预览和公共分享页面的安全边界、模型接入及其他标准协议未作全面审计或改造；CSV 下载使用已鉴权 fetch，不受单文件链接限制。
- 本题必做功能无已知未完成项；未向上游 Keepstack 提 PR，未进行线上部署。未提交数据库、上传文件、凭据、虚拟环境。
- 本次使用 AI 编程工具协助实现和验证，保留 MIT 许可与原作者声明。
