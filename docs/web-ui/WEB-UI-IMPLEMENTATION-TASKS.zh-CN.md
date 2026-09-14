# Worktree Review Web UI 双 Agent 实施任务书

- 状态：可派发
- 制定日期：2026-09-09
- 演示目标：2026-09-10
- 项目经理：主 Agent
- 执行资源：Agent A、Agent B
- 交叉审阅：Frontend/Backend 计划审阅均无剩余 blocker
- 设计基线：`.ai-docs/WEB-UI-DESIGN.zh-CN.md`
- 产品基线：`docs/PRD.zh-CN.md`、`docs/TECH-DESIGN.zh-CN.md`
- 人工 PM 使用指南：`.ai-docs/WEB-UI-HUMAN-PM-GUIDE.zh-CN.md`

## 1. 目标与交付策略

本计划把目标拆成四个可验收里程碑：

1. 先完成可离线运行的高保真 Web 原型，服务 9 月 10 日现场演示。
2. 再接通本地 ReviewApplicationService、SQLite、SSE 和真实检视启动。
3. 随后接入 Session Insight 原生观测。
4. 最后完成最基本的 GitHub PR → Worker → Check → Web Detail 闭环。

9 月 10 日的硬切线是“稳定、可信、可重复”。不能为了赶演示把尚未接通的远程能力伪装成
可用。原型使用 mock 时必须全局显示 `Mock data · Pre-Alpha`；正式演示结果快照必须来自真实
Pipeline，并通过当前结果 Schema 校验。

## 2. 当前项目基线

制定本计划时：

- 当前分支：`master`。
- 当前 HEAD：`08604ad`。
- Python Core、CLI、FastAPI 入口、GitHub webhook/retry/checks 的部分基础已经存在。
- 尚无 `frontend/` 工程、本地 Review API、SQLite Run Store、SSE 和 Session Insight Reader。
- 工作树包含用户已有的多处未提交修改，Web UI 设计文档也是新增文件。

因此，第一个管理动作不是直接让两个 Agent 在当前目录同时编码，而是先建立可追溯基线。
禁止为了得到“干净工作树”擅自 reset、checkout、删除或 stash 用户修改。

## 3. 范围优先级

### P0 — 9 月 10 日演示必须完成

- React + TypeScript + Tailwind 的可运行前端。
- 深色默认、浅色、跟随系统三种主题；选择可保持。
- Action-first Dashboard。
- Review Detail 的 Overview、Findings、Coverage、Identity & Provenance 核心内容和交互。
- Attempts、Policies、Usage 保留完整可读的静态只读内容；复杂时间轴动画后移到 P0.5。
- Passed、Blocked、Error 三类可重复 Case。
- Findings 筛选、详情选择、Evidence 查看。
- Retry 与 Bypass 显示目标文案、权限和禁用原因；复杂状态动画与真实提交后移到 P0.5/P2。
- 1280×800、1366×768、1440×900 下无明显布局破坏。
- 无网络可启动、切换 Case 和完成演示。
- 三类截图与一份固定演示脚本。

### P0.5 — 演示后立即补齐的原型深度

- Attempts 的 Authoritative/Superseded/Retry 完整状态动画。
- Bypass Dialog 的完整风险确认交互。
- 平板和移动端深度 QA。
- 全部错误子类型、Loading/Network retry 的浏览器级回归测试。

### P1 — 本地 Web MVP

- 真实本地 Repository 登记与校验。
- 真实 Provider Profile 和可信 Review/Compute Policy 配置，Secret 只保存环境变量引用。
- 从 Web 创建本地 Attempt。
- 共享 Application Service、SQLite、后台 worker、SSE。
- 刷新、重连和服务重启后仍能查询运行与结果。
- Session Journal Writer。

### P2 — Session Insight 与基础 GitHub

- Session Insight `worktree-review` Reader、实时追尾和深链接。
- GitHub App installation token。
- 受控 Repository mirror/review worktree。
- webhook → authoritative Attempt → worker → Pipeline → Check。
- Check `details_url` 跳转统一 Review Detail。
- Authoritative/Superseded 与 Retry 的真实 UI 投影。

### P3 — 后续增强

- 授权 Bypass 的真实后端流程与 Audit Log。
- 全局搜索、云端 Repository 管理、完整 Provider 健康探测。
- OpenTelemetry exporter、跨候选 Finding 生命周期、外部 fork PR。
- 自动修复、提交或推送不在当前规划内。

## 4. 两个 Agent 的职责

为了同时满足明天的 UI 演示和后续长期可维护性，角色按波次切换，但同一波次不共享文件
所有权。

### Agent A — 原型基础 → Runtime/GitHub

演示波次负责：

- 前端工程脚手架、设计 Token、主题、Application Shell。
- Dashboard、共享领域 View Model、Data Source 边界和 Fixture 装载。

演示完成后负责：

- Python Application Service、ReviewEvent、Store、Worker、Web API 和 SSE。
- Session Journal Writer。
- GitHub App token、Repository mirror、Worker 和 Check 发布闭环。

### Agent B — Review Detail → Web/Session Insight

演示波次负责：

- Review Detail 全部标签页、Findings/Evidence、关键 Dialog 和状态展示。
- Detail 侧响应式、键盘可达性和交互测试。

演示完成后负责：

- 前端 `live` Data Source、New Review、Repositories、Providers、Policies。
- SSE 重连、实时状态和 GitHub 权威状态 UI。
- Session Insight 仓库中的 `worktree-review` Reader 与深链接。

### 项目经理 — 契约、集成与放行

- 确认基线、建立集成分支和两个隔离 worktree。
- 冻结共享契约并处理变更请求。
- 独占共享清单、跨 Agent 文件和最终路由集成。
- 按 Gate 合并，不按“代码写完了”口头状态合并。
- 维护风险、切线和演示脚本。

## 5. 分支、Worktree 与文件所有权

### 5.1 启动规则

G0 放行前由项目经理完成：

1. 将当前 dirty tree 中的修改分成“本轮基线”“用户暂存工作”“不相关修改”。
2. 先取得用户对提交当前已有修改的明确授权，再在不丢失用户改动的前提下形成基线 commit；
   本任务书本身不构成 git commit 授权。
3. 从该 commit 建立集成分支，例如 `integration/web-ui`。
4. 为 Agent A、Agent B 建立独立 branch 和 worktree。
5. 在任务卡中记录确切 base commit；两个 Agent 不得直接共用当前 checkout。

### 5.2 演示波次所有权

| 路径 | 所有者 | 规则 |
| --- | --- | --- |
| `frontend/package.json`、lockfile、Vite/TypeScript/Tailwind 配置 | Agent A | G1 后冻结；新增依赖先提变更请求 |
| `frontend/src/app/**`、`frontend/src/styles/**` | Agent A | 不含下列 Router 文件 |
| `frontend/src/app/router.tsx` | 项目经理 | Agent A 建空路由；PM 负责最终组装 |
| `frontend/src/components/application-shell/**` | Agent A | Agent B 只消费公开组件 |
| `frontend/src/components/ui/**` | Agent A | 通用 primitive；禁止 Detail 私自复制一套 |
| `frontend/src/domain/**`、`frontend/src/data/**` | Agent A | 契约冻结后变更需项目经理批准 |
| `tests/fixtures/demo-repositories/**` | Agent A | 仅用于 A-015 的固定轻量 Repository |
| `frontend/src/features/overview/**` | Agent A | Dashboard 独占 |
| `frontend/src/pages/OverviewPage.tsx` | Agent A | Dashboard 独占 |
| `frontend/src/features/review-detail/**` | Agent B | Review Detail 独占 |
| `frontend/src/pages/ReviewDetailPage.tsx` | Agent B | Review Detail 独占 |
| `frontend/tests/e2e/review-detail*` | Agent B | Detail 场景独占 |
| `docs/**`、根目录 README | 项目经理 | Agent 提交建议，不直接改 |

Agent A 在演示版本合并后停止修改 `frontend/`；从本地 MVP 开始，`frontend/` 全部移交 Agent B。

### 5.3 本地 MVP 以后所有权

| 路径 | 所有者 | 规则 |
| --- | --- | --- |
| `src/worktree_review/application/**` | Agent A | 应用服务、事件、Store Protocol |
| `src/worktree_review/platform/web/**` | Agent A | API DTO、SQLite、SSE、配置 |
| `src/worktree_review/platform/session_insight/**` | Agent A | 只负责 Worktree Review 侧 Writer |
| `src/worktree_review/server/**` | Agent A | App 组合与静态资源服务 |
| `src/worktree_review/platform/github/**` | Agent A | GitHub 闭环 |
| `tests/application/**`、`tests/platform/web/**` | Agent A | Python 新功能测试 |
| `frontend/**` | Agent B | 演示合并后全量接管 |
| Session Insight 仓库的 Reader 文件 | Agent B | 独立仓库、独立分支、遵守该仓库 AGENTS.md |
| `src/worktree_review/core/**` | 项目经理审批 | Agent A 可提最小修改，不能顺手重构 |
| `pyproject.toml`、Schema、共享生成脚本 | 项目经理集成 | 防止依赖和契约并发冲突 |
| `.github/workflows/**` | 项目经理 | Agent 只提交 CI 需求和失败证据 |

## 6. G0：共享契约冻结

两个 Agent 正式并行前必须冻结以下内容。契约文档由项目经理维护，Agent 不得单方面改变。

### 6.1 路由

- `/`：重定向 `/overview`。
- `/overview`：Action-first Dashboard。
- `/reviews/:attemptId`：统一 Review Detail。
- Prototype Case 通过受控 demo selector 或 query 切换，不为 production 导航增加虚假入口。

### 6.2 前端 View Model

至少冻结以下完整领域名称：

- `ReviewSummaryView`
- `ReviewRunView`
- `ReviewSourceView`
- `LocalReviewSourceView`
- `GitHubPullRequestSourceView`
- `GateDecisionView`
- `ReviewFindingView`
- `EvidenceSpanView`
- `CoverageView`
- `ReviewDimensionView`
- `ReviewAttemptView`
- `ReviewIdentityView`
- `PolicySnapshotView`
- `ReviewUsageView`
- `ProviderHealthView`
- `AvailableReviewActionsView`

`ReviewRunView` 分别暴露：

- `runStatus`
- `gateState`
- `authority`
- `publicationStatus`
- `bypassState`

不得把这些状态压进一个含义不明的 `status`。

完整枚举冻结为：

- `runStatus`：`queued`、`preparing`、`running`、`completed`、`failed`、`interrupted`。
- `gateState`：`awaiting_review`、`in_progress`、`passed`、`passed_with_bypass`、`blocked`、`error`。
- `authority`：`local_non_authoritative`、`authoritative`、`superseded`、`audit_only`。
- `publicationStatus`：`not_applicable`、`queued`、`in_progress`、`published`、`failed`。
- `bypassState`：`none`、`active`、`invalidated`。

`AvailableReviewActionsView` 为 Retry、Bypass、Open Check 和 Open Session Insight 分别提供
`visible`、`enabled` 与 `disabledReason`。能力由 Surface、运行终态、Authority、Gate 和部署认证
共同决定，组件不得只根据颜色或按钮位置猜权限。

### 6.3 Source Union

`ReviewSourceView` 使用明确 discriminated union：

- `local-worktree`
- `local-recent-commits`
- `local-committed-ref`
- `github-pull-request`

本地来源不显示 PR、Authoritative 或 Bypass；GitHub 来源不显示任意本地绝对路径。

### 6.4 Fixture

固定三组稳定 Case Key：

- `passed`
- `blocked`
- `error_merge_conflict`

每个 Case 在数据内部另有独立 `attemptId`；Blocked 主展示 Case 使用
`attempt_01JY8R7F2W`。Case Key 与 Attempt ID 不得混用。

Blocked Case 使用：

- Repository：`acme/payment-service`
- PR：`#184 Harden webhook authorization`
- Proposed：`feature/webhook-auth`
- Target：`main`
- Review Policy：`1.3.0`
- Provider/Model：`openai / gpt-5.6`
- Required Coverage：Complete
- Cost：`$0.42`
- Duration：`2m 18s`
- 三个设计文档已定义的真实场景 Finding。

### 6.5 Attempt 与事件契约

- Attempt ID 在入队和 Pipeline 执行前只分配一次。
- Event schema：`worktree-review.event/v1`。
- `sequence` 在 Attempt 内从 1 严格递增。
- Event 先持久化，后广播。
- SSE `id` 等于 sequence，并支持 `Last-Event-ID`。
- Provider 事件只在真实可观测调用边界产生。

### 6.6 设计 Token 与状态

- 深色为首次默认；同时支持浅色与 system。
- Blocked 使用红橙，Error 使用深红，Warning 使用黄色，Bypass 使用琥珀，Passed 使用绿色，
  Passed with Bypass 使用带琥珀风险提示的绿色组合 Token。
- 黄色或琥珀只表示警告、风险接受或非阻断注意，不是新的 Gate 结果。
- 所有状态必须同时使用图标、文字和颜色。

## 7. 波次 0：基线和并行启动

### PM-001 — 建立可追溯基线

- 优先级：P0。
- 所有者：项目经理。
- 依赖：无。
- 交付：基线 commit、集成分支、两个 Agent branch/worktree、任务卡。
- 验收：任何现有用户修改均未丢失；每个 Agent 能报告相同 base commit。

### PM-002 — 发布 G0 契约包

- 优先级：P0。
- 所有者：项目经理。
- 依赖：PM-001。
- 交付：契约文档、Fixture JSON 草案、路由、Token 名称、组件导入边界，以及完整 P0 依赖清单。
- 依赖清单固定 React Router、Framer Motion、Lucide、Recharts、Vitest、Testing Library、
  Playwright 和 `prism-react-renderer`；Evidence Viewer 不得临时引入第二套高亮器。
- 验收：Agent A/B 能在不修改同一文件的前提下开始工作。

### A-001 — 最小前端地基

- 优先级：P0，关键路径。
- 所有者：Agent A。
- 依赖：PM-002。
- 大小：S。
- 工作：创建 Vite React TypeScript 工程、Tailwind、Router、测试框架、空页面、构建脚本，安装
  PM-002 冻结的全部依赖并提交 lockfile，以及提供 G0 已冻结的 TypeScript interface 与稳定
  Fixture export 名称。
- 交付：一个尽量小的 foundation commit，优先在开始后第一检查点交给项目经理。
- 验收：Overview 和 Review Detail 空路由可访问；lint、typecheck、unit test、build 命令可执行。

A-001 只是地基，不是 Agent B 的正式开工点。Agent A 继续完成 A-010 与 A-012，PM-003 完成
foundation handoff 后，A/B 才进入可持续、可编译的并行阶段。

## 8. 波次 1：9 月 10 日高保真原型

Agent A 的强制先后顺序是 A-010 → A-012 → PM-003；交接后 A 继续 Shell/Dashboard，B 同时
开始 Detail。不得为了“并行”让 Agent B 自建第二套 Token、Fixture 或 domain type。

### Agent A 任务

#### A-010 — 语义 Token、主题与基础组件

- 优先级：P0。
- 依赖：A-001。
- 大小：M。
- 交付：色彩、间距、字体、圆角、边框、状态 Token；Button、Badge、Tabs、Tooltip、Dialog、
  Skeleton、Empty State 等基础组件。
- 验收：dark/light/system 即时切换并持久化；focus-visible 清楚；reduced-motion 生效。

#### A-012 — 共享 View Model、Fixture 与 Data Source

- 优先级：P0。
- 依赖：A-001、PM-002。
- 大小：M。
- 交付：G0 类型、`ReviewDataSource`、`MockReviewDataSource`、三个 Case、确定性的时间/成本数据。
- 验收：Fixture 不使用 `any`；长 path/hash/error 已覆盖；生产构建不会把 mock 写入运行历史。

### PM-003 — Frontend Foundation Handoff

- 优先级：P0，真正并行的放行 Gate。
- 所有者：项目经理。
- 依赖：A-001、A-010、A-012。
- 交付：把脚手架、依赖 lockfile、Token、UI primitives、TypeScript 契约和最小 type-safe Fixture
  合入集成基线，并将 Agent B worktree 更新到该 commit。
- 验收：Agent B 无需修改 manifest、Token、domain 或 data 文件即可独立编译 Review Detail。

### Agent A 继续任务

#### A-011 — Application Shell

- 优先级：P0。
- 依赖：PM-003。
- 大小：M。
- 交付：左侧导航、顶部 Repository switcher、搜索占位、Provider freshness、主题、用户/环境菜单、
  New Review 主动作。
- 验收：1280px 和 1440px 下信息层级稳定；窄屏导航可用；Prototype 状态全局可见。
- P0 行为：Search 隐藏；尚未实现的 New Review、Repository、Provider 和导航入口显示 Preview/
  disabled 状态及可访问说明，不能形成无响应控件。

#### A-013 — Action-first Dashboard

- 优先级：P0。
- 依赖：A-011、A-012。
- 大小：L。
- 交付：Needs Attention、Active Reviews、Recent Attempts、状态统计、Token/Cost 趋势、Policy 使用、
  Provider 健康。
- 验收：行动项在首屏先于统计；图表只用于趋势；统计分母和 unknown cost 表达正确。

#### A-014 — 原型构建与 Dashboard 视觉 QA

- 优先级：P0。
- 依赖：A-013。
- 大小：S。
- 交付：两主题截图、无网络启动记录、Dashboard 键盘检查。
- 验收：1280×800、1366×768 和 1440×900 不横向溢出；正文对比度可读。

#### A-015 — 真实 Demo Snapshot 生成与校验

- 优先级：P0，演示放行条件。
- 依赖：当前 CLI/Pipeline、A-012。
- 大小：M。
- 交付：从三个固定轻量 Repository/场景生成 Passed、Blocked、Error 真实结果；通过当前 JSON
  Schema 自动校验；保存生成时间、schema、Review/Compute Policy、Provider provenance，并映射为
  local source ReviewRunView；提供断网回放测试。
- 验收：真实 local Pipeline snapshot 与手写 GitHub product mock 使用不同 badge 和目录；页面不会
  把模拟 PR metadata 说成 Pipeline 真实来源；Snapshot 可重复装载且不调用网络。

### Agent B 任务

#### B-010 — Review Detail 框架与 Gate Header

- 优先级：P0。
- 依赖：PM-003。
- 大小：M。
- 交付：来源自适应 Header、Gate Status、元数据、七个标签页、Authoritative Attempt 标识。
- 验收：Local/GitHub source 不串字段；状态不只依赖颜色；超长值可复制且不破坏布局。

#### B-011 — Overview、Merge Candidate Path 与 Review Pipeline

- 优先级：P0。
- 依赖：B-010、PM-003。
- 大小：M。
- 交付：Gate/Blocking/Coverage/Cost 四摘要、Review Summary、Dimensions、Provider/Retention，
  以及概念路径和九阶段执行路径；完成、当前、未开始、失败四类节点。
- 验收：明确表达 review exact merge result；Error 节点停止光流并显示安全原因；reduced-motion 可用。

#### B-012 — Findings Master/Detail 与 Evidence Viewer

- 优先级：P0。
- 依赖：B-010、PM-003。
- 大小：L。
- 交付：severity/dimension/evidence/path 筛选、搜索、Blocking only、Finding 选择、证据代码、
  provenance、fingerprint、policy、repair guidance。
- 验收：三个示例 Finding 均可筛选和选择；引用行突出；切换后滚动到证据；没有自动修改按钮。

#### B-013 — Coverage、Attempts、Provenance、Policies、Usage

- 优先级：P0。
- 依赖：B-010、PM-003。
- 大小：L。
- 交付：完整七 Tab；文件级缺失原因；Attempt 时间轴；身份关系图；Policy trust 文案；Usage 明细。
- 验收：Coverage 不以单一百分比掩盖缺失；merge conflict 时不伪造 Review Identity；Superseded
  明确失去门禁权威。

#### B-014 — Retry 与 Bypass 目标交互

- 优先级：P0.5；P0 先交付完整文案、能力状态和禁用原因。
- 依赖：B-010、B-013。
- 大小：M。
- 交付：Retry 确认、Attempt 时间轴过渡、Bypass 风险确认、必填理由和禁用状态。
- 验收：GitHub authoritative Retry 文案明确撤销 standing decision；Local Retry 只说明创建新
  Attempt，不提 standing decision；Error、Superseded 和未授权状态不可 Bypass；Bypass 不表现成
  问题已解决；mock 交互不发真实远程请求。

#### B-015 — Detail 状态、响应式与可访问性 QA

- 优先级：P0。
- 依赖：B-011、B-012、B-013；P0.5 的 Dialog 动画回归另依赖 B-014。
- 大小：M。
- 交付：Loading、Skeleton、Empty、Network retry、Awaiting、In Progress、Passed without Finding、
  Blocked、Coverage Error、Merge Conflict、Provider Failure、Budget Exhausted、Superseded、Passed
  with Bypass 状态；每项绑定 deterministic state switch 或 Fixture。
- P0 验收：Passed、Blocked、Merge Conflict 在浏览器完成；其余状态至少通过组件级 deterministic
  test。P0.5 再把完整矩阵提升为浏览器回归，并完成 Dialog 与移动端深度 QA。
- 验收：键盘可以完成 Tab、筛选和选择；Tooltip 可聚焦；窄屏转换为列表而非挤压表格。
- Network retry 只续传当前 Attempt 的事件，不得创建新 Attempt。

### PM 集成任务

#### PM-010 — 原型集成

- 优先级：P0，关键路径。
- 依赖：A-014、B-015。
- 交付：Router 组装、冲突处理、统一 Case selector、统一 Mock/Pre-Alpha 标识。
- 合并顺序：A-001 → A 的共享基础 → B 的 Detail → A 的 Dashboard → PM 集成修正。
- 验收：Agent B 无需修改 Agent A 所有的共享文件；任何契约差异均已显式解决。

#### PM-011 — 演示包

- 优先级：P0。
- 依赖：PM-010、A-015。
- 交付：Passed、Blocked、Error 三类截图；固定点击脚本；绑定 loopback 的 Vite Preview 离线
  启动说明；已知限制清单。
- 验收：完整演示不需要 Provider、GitHub 或 Session Insight 在线；所有远程能力都有 Pre-Alpha
  状态说明；页面不暗示未接通功能已正式可用。

#### PM-012 — Frontend CI 接线

- 优先级：P0.5，不阻塞首个本地演示包。
- 所有者：项目经理；`.github/workflows/**` 不分配给执行 Agent。
- 依赖：PM-010。
- 交付：在现有 CI 中接入 lint、typecheck、非 watch unit test、build 和关键 Playwright smoke。
- 验收：与本地 Gate 使用同一 npm script；失败能定位到具体命令。

### 演示降级顺序

若时间不足，按以下顺序降级，不能牺牲可信度：

1. 移除非必要 Recharts 图表，保留数值和趋势文字。
2. 减少装饰性动效，保留状态转换与 focus feedback。
3. 将次要 Settings/Audit 页面保留为 capability unavailable。
4. 保留所有 Detail 标签，但次要 Tab 可以使用完整静态数据而非复杂交互。
5. 不得删除 Gate、Finding/Evidence、Coverage、Attempt authority、三类 Case 和主题。

## 9. 波次 2：本地 Web MVP

本波次开始后，Agent A 不再修改 `frontend/`，Agent B 全量接管前端。两人通过冻结的 HTTP DTO
和录制的 API Fixture 并行开发。

### Agent A：应用与 Web 后端

#### A-100 — 外部 Attempt ID 与 ReviewApplicationService

- 优先级：P1，关键路径。
- 依赖：G0。
- 大小：L。
- 工作：允许调用方传入已分配 Attempt ID；CLI 未传时由应用服务分配；把 CLI、Web、GitHub
  的准备与执行路径收敛到应用服务；新增明确的 `ReviewExecutionContext.repository_path`，所有 Git
  操作使用受信任执行路径，而 ReviewRequestKey/Identity 保留 canonical repository identity。
- 临时文件授权：项目经理可仅为本任务授权 Agent A 修改 `core/pipeline.py`、`core/identity.py`、
  `core/candidate.py`、`core/review_worktree.py`、`core/context.py` 及相应测试；不得借机重构无关 Core。
- 验收：同一运行在 Store、ReviewEvent、ReviewReport、Journal 中 ID 一致；CLI 行为不回归；
  identity 字符串从不被隐式 `Path(...)`；契约测试覆盖 identity/path 分离。

#### A-101 — 生命周期与 Surface DTO

- 优先级：P1。
- 依赖：A-100。
- 大小：M。
- 交付：run/gate/authority/publication/bypass 分轴模型，Local/GitHub discriminated union，
  `AvailableReviewActionsView` 和 `ReviewRunView` mapper。
- 验收：Core ReviewReport 不包含 PR、Author、Check 或本地 UI 字段；UI 状态是确定性投影。

#### A-102 — 有序 ReviewEvent Recorder

- 优先级：P1，关键路径。
- 依赖：A-100。
- 大小：L。
- 交付：v1 类型、per-Attempt sequence、persist-before-broadcast、脱敏、真实 progress 映射，以及
  derive/check-completeness/evaluate-gate/publish 在内的完整九阶段 hook。若某节点只能从终态
  ExecutionRecord 回填，事件必须标记为 reconstructed，而不是冒充实时事件。
- 验收：并发事件顺序稳定；权威 Event/Result Store 失败使应用交付失败；只有 Journal/log/OTel
  旁路 Sink 可降级告警；不存在伪造 provider_call 或 Finding lifecycle 事件。

#### A-103 — SQLite ReviewRunStore 与迁移

- 优先级：P1。
- 依赖：A-101、A-102。
- 大小：L。
- 交付：repositories、provider_profiles、trusted policies、review_runs、review_events、review_results、
  idempotency_records、settings；事务性 `create_attempt_with_initial_event_and_idempotency`、查询和
  Overview 聚合。
- 验收：规范 Result JSON 不可变；Retry 新建 Attempt；unknown cost 不保存为零；重启可查询。

#### A-104 — Repository、Provider Profile、Policy Registry 与信任边界

- 优先级：P1。
- 依赖：A-103。
- 大小：L。
- 交付：真实 root 校验、symlink 防漂移、三种 local source、Provider Profile CRUD、显式连接
  测试，以及可信位置的 Review/Compute Policy 只读登记、列表和详情。
- 验收：浏览器不能提交未登记任意路径；Secret 值不进入响应、日志、事件或 Journal；可信配置
  不从被审查 Repository 读取。

#### A-105 — Review/Overview API 与幂等创建

- 优先级：P1。
- 依赖：A-101、A-103、A-104。
- 大小：L。
- 交付：设计文档 16 节 Review、Repository、Provider Profile、Policy、Overview API，稳定 error
  code、`Idempotency-Key`、CSRF/Origin/Host 防护。
- 验收：Attempt 和首事件持久化后才返回 202；相同 key 同请求返回原 Attempt，不同请求冲突。

#### A-106 — 后台 Worker、SSE 与重启恢复

- 优先级：P1，关键路径。
- 依赖：A-102、A-103、A-105。
- 大小：L。
- 交付：默认并发 1 的队列、慢客户端隔离、heartbeat、Last-Event-ID、Interrupted 恢复。
- 验收：回放与订阅切换不丢事件；刷新和断线不丢进度；HTTP request 不直接运行 Pipeline。

#### A-107 — Session Journal Writer 与静态前端服务

- 优先级：P1。
- 依赖：A-102、A-106。
- 大小：M。
- 交付：三个版本化 Schema、metadata heartbeat/last sequence、events/result 原子/追加语义、从
  Event Store 按 sequence 回补，以及 FastAPI 服务 production build。
- 验收：长 Provider 调用仍更新 heartbeat；Journal 故障只告警；本地 Web MVP 只需一个服务
  进程；默认监听 loopback；缺失静态资源返回清晰启动错误而非空白页。

#### A-108 — Review Detail 数据投影补全

- 优先级：P1。
- 依赖：A-101、A-102；Core 修改需项目经理逐文件批准。
- 大小：M。
- 交付：为 Coverage 增加稳定的每文件 category/reason/rule 投影；为 Usage 增加可验证的
  dimension/call ordinal/elapsed 关联。若底层数据不存在，View 明确返回 unknown/not-reported，
  不从数组位置猜测。
- 验收：Live Coverage/Usage 满足设计文档 13.6/13.10；Schema 演进兼容现有 CLI Result。

#### PM-101 — Frontend Production Packaging

- 优先级：P1。
- 所有者：项目经理，Agent A 提供所需构建产物约定。
- 依赖：A-107、稳定 frontend build。
- 交付：dist 复制位置、Hatch package-data、server 启动路径和缺资源错误行为。
- 验收：从 wheel/sdist 安装后可由一个 FastAPI 进程打开 Web UI；源代码 checkout 不是隐含前提。

### Agent B：真实前端能力

#### B-100 — LiveReviewDataSource 与 SSE 状态机

- 优先级：P1，关键路径。
- 依赖：冻结 DTO；可先用录制响应并行。
- 大小：L。
- 交付：API client、SSE replay/reconnect、view mapper、mock/live 明确切换。
- 验收：重复 sequence 去重；断线提示与重试可见；实时更新不会清空当前选中 Finding。

#### B-101 — New Review

- 优先级：P1。
- 依赖：B-100。
- 大小：L。
- 交付：Repository、source、Target、Review Policy、Compute Policy、resolved Provider Profile 和
  budget/disclosure 确认。
- 验收：提交前展示数据目的地和 retention；重复提交使用幂等键；字段错误就地显示。

#### B-102 — Repositories

- 优先级：P1。
- 依赖：B-100。
- 大小：M。
- 交付：授权列表、登记、状态、移除授权。
- 验收：移除授权文案明确“不删除 Repository”；路径截断不隐藏关键身份。

#### B-103 — Provider Connection Profiles

- 优先级：P1。
- 依赖：B-100。
- 大小：M。
- 交付：只包含 provider、endpoint/local adapter、credential reference 和 health 的 Profile CRUD，
  以及显式 Test Connection；不在此处复制 model、budget 或 retention。
- 验收：前端从未接收 secret；测试连接有 loading/success/error；未知价格不显示为 `$0.00`。

#### B-104 — Review/Compute Policies

- 优先级：P1。
- 依赖：B-100。
- 大小：M。
- 交付：Review Policy 的 Dimensions/blocking/evidence/context，以及 Compute Policy 的 provider
  profile 引用、model、token、budget、pricing、destination、retention 展示。
- 验收：清楚区分 Review Policy 与 Compute Policy；显示 Repository 内容不可信的提示。

#### B-105 — Live Detail 与 Overview 接线

- 优先级：P1。
- 依赖：B-100 至 B-104，A-105/A-106 最终联调。
- 大小：L。
- 交付：用真实 API/SSE 替换 mock、运行中阶段、终态跳转、错误恢复。
- 验收：本地 Attempt 不显示 standing decision/Bypass；页面刷新保持 Attempt；三种真实终态正确。

### PM-100 — 本地 MVP 联调 Gate

- 依赖：A-107、A-108、B-105、PM-101。
- 验收：登记真实 Repository → 创建 Review → 实时进度 → 终态结果 → 刷新回看完整闭环；CLI
  与 Web 对同一 resolved inputs 产生相同 Core 语义；三类离线演示仍可用。

## 10. 波次 3：Session Insight 与基础 GitHub 并行

本波次两条轨道真正独立：Agent A 主要在 Worktree Review 仓库完成 GitHub；Agent B 主要在
Session Insight 独立仓库完成 Reader。共同依赖是稳定 ReviewEvent/Journal 契约。

### Agent A：基础 GitHub

#### A-200 — GitHub App Installation Token Provider

- 优先级：P2，关键路径。
- 依赖：A-100、A-101。
- 大小：L。
- 交付：App private key 签名、installation token 获取/缓存/刷新、最小权限与脱敏。
- 验收：运行时按 Installation ID 获取短期 token；静态 PAT 仅保留为显式 Pre-Alpha smoke 模式。

#### A-201 — GitHub Result/Event/Publication Persistence

- 优先级：P2，关键路径。
- 依赖：A-101、A-102 和现有 Postgres AuthoritativeAttemptStore。
- 大小：L。
- 交付：PostgreSQL review events/results、AttemptExecutionSnapshot、check_run_id、publication status、
  idempotency 和 publication intent/outbox 的迁移与 Store 实现。
- 验收：queued Check 和执行快照可在 worker 启动前恢复；远程发布失败可安全重试且不会重复发布
  standing decision。

#### A-202 — GitHub Trigger Coordinator 与执行快照

- 优先级：P2，关键路径。
- 依赖：A-200、A-201。
- 大小：L。
- 交付：处理 opened、reopened、synchronize、ready_for_review、converted_to_draft、base retarget 和
  target branch push；持久化包含 request key、resolved refs、Review/Compute Policy snapshot、Provider
  Profile reference、installation/delivery 的不可变 `AttemptExecutionSnapshot`；创建 queued Check 并
  保存 check_run_id 后才入队。
- 验收：draft/retarget/target branch 或 Policy 变化能撤销不再适用的 standing decision；重复
  delivery 不产生并列权威 Attempt；凭据值不进入 snapshot。

#### A-203 — Repository Mirror Manager

- 优先级：P2，关键路径。
- 依赖：A-200。
- 大小：L。
- 交付：installation/repository 隔离 mirror、fetch 指定 OID、受控 `repository_path`、清理策略。
- 验收：Repository full name 不被当作 Path；PR 内容不能指定目录；base/head OID 执行前复核。

#### A-204 — Authoritative Worker 到 Pipeline

- 优先级：P2，关键路径。
- 依赖：A-100、A-102、A-202、A-203。
- 大小：L。
- 交付：claim durable job、从不可变执行快照恢复输入、更新既有 Check 为 in-progress、使用预创建
  Attempt ID 调用共享服务并保存终态报告。
- 验收：worker 不在 claim 后重新读取可漂移的当前 Policy；旧 Attempt 可以完成审计但不能发布。

#### A-205 — Check 终态、Outbox 与 CAS 发布

- 优先级：P2。
- 依赖：A-201、A-204。
- 大小：L。
- 交付：更新既有 Check 为 terminal、summary、有限 annotation、details_url、outbox retry。
- 验收：发布前再次校验 authority；远程发布失败记录 publication failure，但不改写 Core Gate；
  重试更新同一个 check_run_id，不创建无界重复 Check。

#### A-206 — GitHub Retry E2E

- 优先级：P2。
- 依赖：A-202、A-205。
- 大小：M。
- 交付：GitHub Checks requested action 授权 Retry、新权威 Attempt、旧 Attempt superseded、审计字段。
- 验收：standing decision 撤销清晰；晚到旧结果不能覆盖新 Check。

### Agent B：Session Insight Reader

#### B-200 — Reader 契约与 Fixture

- 优先级：P2。
- 依赖：A-107 的 Journal 契约。
- 大小：M。
- 工作目录：独立 Session Insight 仓库。
- 交付：`worktree-review.session-metadata/v1`、`worktree-review.event/v1`、
  `worktree-review.cli.result/v1` Fixture 和兼容规则、metadata/events/result 容错规则、稳定 Session
  ID 映射。
- 验收：先阅读并遵守该仓库 `AGENTS.md`；损坏/半写文件不导致旧 Session 被误删。

#### B-201 — `worktree-review` Reader

- 优先级：P2，关键路径。
- 依赖：B-200。
- 大小：L。
- 交付：AgentType、DisplayName、ListSessions、RenderANSI、ListSessionsDetailed、GetSession、
  GetRenderEvents、WatchRoots、LiveRevision、SessionLive，以及 Capabilities、Presentation、Reader
  registry 和 Discover 注册。
- 验收：通过 BaseSessionReader conformance tests；一个 Attempt 只对应一个 Session；阶段、
  Dimension、Usage、Finding、Gate 可回放。

#### B-202 — 实时追尾与 Child Session

- 优先级：P2。
- 依赖：B-201。
- 大小：M。
- 交付：JSONL 增量读取、live 状态、可验证 child_agent_type/session_id 关联。
- 验收：不能可靠取得 ID 时留空，不按进程时间或模型名猜测。

#### B-203 — Web 深链接与能力状态

- 优先级：P2。
- 依赖：B-201；可与 A-202 并行。
- 大小：M。
- 交付：已连接、未连接、版本不兼容、观测关闭四态；稳定格式
  `#/session/worktree-review/<attempt-id>` 的 Review Detail 深链接。
- 验收：Session Insight 不可用不影响 Review Gate；版本能力和最后探测时间可见。

#### B-204 — GitHub Live UI 投影

- 优先级：P2。
- 依赖：A-205 的稳定 DTO；可先用契约 Fixture。
- 大小：M。
- 交付：PR source、Check 链接、Authoritative/Superseded、publication status；P2 Retry 引导到
  GitHub Checks requested action。本地单用户 Web 没有可证明的 GitHub actor，Web Retry 保持禁用
  并说明需要部署认证。
- 验收：本地与 GitHub 使用同一 Detail；旧 Attempt 明确不能覆盖 standing decision；浏览器不会
  把本地用户冒充成 GitHub 授权 actor。

### PM-200 — 两条集成 Gate

分别验收，不相互阻塞：

- Session Insight Gate：本地 Web Attempt 能实时出现并完整回放；关闭 Session Insight 后 Review
  仍正常完成。
- GitHub Gate：同仓库 ready PR 自动产生权威 Attempt，Check 完成并跳转 Web Detail；重复 delivery
  和晚到旧 Attempt 不能覆盖当前结论。

## 11. 波次 4：授权 Bypass 与审计

### A-300 — Bypass Domain、授权和失效

- 所有者：Agent A。
- 优先级：P3。
- 依赖：A-206 以及可验证的部署用户/GitHub actor 认证映射。
- 交付：逐 Finding fingerprint 的风险接受、非空理由、actor、Review Identity/Policy 变化失效。
- 验收：只允许完整 GitHub review 的 blocking Finding；Error 不可 Bypass。

### A-301 — Audit Event Store/API

- 所有者：Agent A。
- 优先级：P3。
- 依赖：A-300。
- 交付：retry、authority、publication、bypass 审计事件和分页 API。
- 验收：审计事件不可通过普通 UI 修改；不包含 secret 或完整源代码。

### B-300 — Bypass 与 Audit UI 接线

- 所有者：Agent B。
- 优先级：P3。
- 依赖：A-300、A-301。
- 交付：真实 Bypass Dialog、风险摘要、Audit Log 页面。
- 验收：文案固定表达“接受风险，不代表问题已解决”；失效原因清晰。

## 12. 合并 Gate 与验证命令

### 12.1 每个任务的最小交付

每个 Agent 交付必须包含：

- 任务 ID 和目标。
- base commit 与交付 commit。
- 修改文件清单。
- 实际执行的测试及结果。
- UI 任务的截图或录屏路径。
- 契约变化、已知限制和下一任务依赖。
- 不属于自己文件所有权的改动必须单独列出并说明原因。

### 12.2 Python Gate

在项目脚本未另行统一前，至少执行：

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest
git diff --check
```

如果完整测试依赖 PostgreSQL、网络或外部服务，Agent 仍需运行全部不依赖外部状态的测试，并
精确报告未运行项及原因，不能只写“测试通过”。

### 12.3 Frontend Gate

脚手架必须提供以下非交互式语义脚本。P0 由项目经理在合并前手工执行；PM-012 完成后再由 CI
固定执行：

```bash
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run preview -- --host 127.0.0.1
```

`test` 必须映射到 `vitest run`，不能进入 watch mode；`test:e2e` 必须映射到 `playwright test`。
Preview 只绑定 loopback，运行时不得请求 registry、CDN、Provider 或其他外网资源。

关键演示路径另做浏览器级验证：

- Dashboard → Blocked Review。
- Finding 筛选 → Evidence。
- Coverage/Attempts/Identity 标签页。
- P0：Retry/Bypass 的 capability 与禁用原因；P0.5：确认与取消动画。
- Error 不显示 Bypass。
- dark/light/system 与 reduced-motion。

### 12.4 合并拒绝条件

出现以下任一情况不得合并：

- 为通过演示伪造“GitHub 已连接”“Session Insight 已连接”或 Provider 实时状态。
- Gate、Finding 或权威状态只能靠颜色识别。
- 浏览器收到 API Key、环境变量值或未脱敏异常。
- Retry 覆盖旧 Attempt，或不同系统为同次运行生成不同 Attempt ID。
- SSE 可能在 replay/subscribe 切换时漏事件且没有重连恢复保证。
- GitHub 把 Repository full name 直接当作本地 Path。
- Agent 修改了不属于当前任务的用户文件，且没有说明和批准。
- 只验证 happy path，没有 Passed、Blocked、Error 三态。

## 13. 依赖关系与关键路径

```text
PM-001 基线
  → PM-002 契约
    → A-001 前端地基
      → A-010 + A-012 → PM-003 Foundation Handoff
        ├─→ A-011 → A-013/014 ─────────────┐
        ├─→ A-015 真实 Snapshot ───────────┼→ PM-010/011 演示
        └─→ B-010/011/012/013/015 ─────────┘
             └─→ B-014 + PM-012（P0.5）

PM-002
  → A-100 Application Service
    → A-101 状态/DTO + A-102 Event Recorder
      → A-103/104/105/106/107/108 + PM-101 ─┐
      → B-100/101/102/103/104/105 ─┴→ PM-100 本地 Web MVP

A-107 Journal ─→ B-200/201/202/203 ─→ Session Insight Gate
A-100/102 ─→ A-200 + A-201 → A-202/203 → A-204/205/206 ─→ GitHub Gate
A-205 DTO ─→ B-204 ───────────────────────────────────────┘
```

演示关键路径是 `PM-001 → PM-002 → A-001/A-010/A-012 → PM-003 → 两路 UI 并行 →
PM-010/PM-011`。
长期产品关键路径是 `Attempt ID → Event Recorder → Store/API/SSE → GitHub Worker/Session Reader`。

## 14. 风险与应对

| 风险 | 信号 | 应对 |
| --- | --- | --- |
| Dirty tree 导致误覆盖 | Agent 无法说清 base commit | G0 前不启动编码；禁止擅自 reset/stash |
| 前端共享文件冲突 | 两个 Agent 同改 Router/Token/types | A-001 先合并；严格文件所有权；PM 组装 Router |
| UI 范围过大拖垮演示 | 次要页面阻塞核心 Detail | 按演示降级顺序切线，保留 Gate/Evidence/Coverage/Attempt |
| Mock 被误认为真实能力 | 页面没有环境标识 | 全局 `Mock data · Pre-Alpha`，远程动作不发请求 |
| Core 与 Web/GitHub 语义分叉 | Adapter 自算 Gate 或 Identity | 只由 Core 产出；Surface 使用 `ReviewRunView` 投影 |
| Attempt 关联断裂 | Store、Pipeline、Check ID 不同 | 外部预分配并贯穿；契约测试 |
| 实时事件丢失 | 重连后 sequence 出现缺口 | persist-before-broadcast；水位线；Last-Event-ID |
| 观测反向影响 Gate | Journal/SI 故障导致 Review Error | 旁路 best-effort，单独 health/warning |
| GitHub token 越权或泄漏 | 使用全局 PAT、日志出现 token | installation token、最小权限、脱敏测试 |
| Repository identity/path 混用 | full name 被传给 Git 命令作目录 | Mirror Manager 只返回受控 `repository_path` |
| 权威旧结果覆盖新结果 | superseded Attempt 仍发布 Check | 终态发布前 CAS；并发与晚到测试 |

## 15. Definition of Done

### 演示 DoD

- 前端可从 clean checkout 完成依赖安装与构建；依赖安装可以访问 registry，但构建产物的运行
  和完整演示不得产生外网请求。
- Dashboard 和 Review Detail 均完成，不是只有首页。
- Passed、Blocked、Error 可在固定入口重复打开。
- Blocked Case 能完整讲清候选、阶段、Finding、Evidence、Coverage、Gate、Attempt 和成本。
- 两主题可用，状态不只靠颜色，关键交互支持键盘；至少验证 1280×800、1366×768、1440×900。
- 所有可见按钮都有实际反馈；尚不可用的能力必须禁用并解释原因，不能保留无响应按钮。
- 截图、演示脚本、已知限制齐备。

### 本地 Web MVP DoD

- 用户能登记真实 Repository 和 Profile，并从 Web 发起一次真实检视。
- Attempt 在 1 秒内持久化可查询，Pipeline 不运行于请求生命周期。
- SSE 可回放、追尾和断线续传；刷新不丢结果。
- Secret 和不可信 Repository 内容不越过设计边界。
- CLI 与 Web 共享 Pipeline 和确定性 Gate 语义。

### Session Insight DoD

- 一个 Review Attempt 对应一个稳定 Session。
- 运行中可见，终态可回放，Child Session 只在证据充分时关联。
- Session Insight 关闭、不可达或不兼容都不改变 Gate。

### 基础 GitHub DoD

- 同仓库 ready PR 触发权威 Attempt 和 queued Check。
- Worker 在受控 mirror/worktree 中调用共享 Pipeline。
- Check 发布前通过 CAS，旧 Attempt 不可覆盖新 standing decision。
- Check 指向统一 Web Detail，页面正确显示权威与发布状态。
- Retry 创建新权威 Attempt，不覆盖历史结果。

## 16. 项目经理检查点

- 检查点 1：G0 基线与契约签收。
- 检查点 2：A-001 地基可构建，Agent B 开始并行。
- 检查点 3：Dashboard 和 Detail 各自完成第一个可点击版本。
- 检查点 4：三 Case、两主题、目标分辨率联合 QA。
- 检查点 5：演示冻结；除阻断缺陷外不再扩范围。
- 检查点 6：本地 API DTO 与前端 live adapter 契约测试通过。
- 检查点 7：Session Insight 与 GitHub 两条轨道分别验收。

每个检查点只回答三件事：当前可演示/可运行的结果是什么、剩余阻断是什么、下一次合并由谁
负责。禁止用“完成百分比”替代可验证的交付物。
