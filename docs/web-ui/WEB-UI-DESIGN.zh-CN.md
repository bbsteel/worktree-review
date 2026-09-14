# Worktree Review Web UI 具体设计

- 状态：已确认设计，等待实施
- 初稿日期：2026-09-08
- 最后更新：2026-09-09
- 目标演示日期：2026-09-10
- 配套文档：`docs/PRD.zh-CN.md`、`docs/TECH-DESIGN.zh-CN.md`
- 范围：本地 Web 检视控制台、Session Insight 可观测性、明暗主题、结果展示、模型配置、
  运行历史与统计，以及后续最基本 GitHub PR 对接
- 规范优先级：本文不得修改 PRD 和 TECH-DESIGN 已定义的 Review Identity、Attempt、
  Finding、Evidence、Gate 或失败关闭语义；若有冲突，以英文 PRD 和英文 TECH-DESIGN 为准

## 1. 背景与目标

为了保证 2026 年 9 月 10 日现场演示稳定，产品必须能够对一个真实本地 Git 仓库执行
完整检视，输出带证据的 Finding、严重度和 Gate 结论，并能稳定重现 Passed、Blocked、
Error 三类结果。Web UI 在此基础上增加图形化启动、实时进度、结果展示、模型配置和历史
统计，但不得形成与 CLI 或 GitHub 不同的产品语义。

本文定义的首版产品是一个本机单用户的 Evidence-first 检视控制台。它首先服务本地真实
检视和稳定演示，并预留共享数据模型与页面组件，使后续 GitHub PR 自动触发和 Check
发布无需重做 Web UI。

### 1.1 当前实现基础

当前仓库已经具备：

- 共享九阶段 Core Pipeline。
- 当前 Worktree、最近 N 次提交、显式 committed ref 三种本地来源。
- Anthropic、OpenAI 与 local-cli Provider。
- Finding、Evidence Span、Coverage、Usage 和确定性 Gate 计算。
- 版本化的 `worktree-review.cli.result/v1` JSON 结果。
- FastAPI 服务入口、GitHub webhook、Attempt 权威状态和 GitHub Check 发布适配器。
- 非权威 Pipeline/Dimension 进度事件。

当前缺少：

- 本地检视 HTTP API。
- Web 前端。
- Web 后台运行协调和运行历史持久化。
- 浏览器实时事件传输。
- Session Insight 对一次完整 Review Attempt 的原生观测。
- GitHub worker 到共享 Pipeline 和 Check 发布的端到端连接。

### 1.2 目标

首版 Web UI 必须：

1. 允许用户选择已授权的本地 Git 仓库并发起检视。
2. 允许用户选择检视来源、Target、Review Policy、Compute Policy 和 Provider Profile。
3. 在模型调用前清楚展示 Provider、Model、数据目的地、保留策略和预算。
4. 实时展示 Pipeline 阶段与 Review Dimension 状态。
5. 优先展示 Gate、Finding、Evidence、影响和修复建议。
6. 展示 Coverage、Usage、Cost、Attempt ID 和策略版本等审计信息。
7. 提供明亮、深色和跟随系统三种主题设置。
8. 保存运行历史并提供定义明确的统计数据。
9. 为 Session Insight 输出可实时读取、可回放的 Review Session Journal。
10. 使用同一详情页展示未来的本地、CLI 导入和 GitHub Attempt。
11. 在无模型和无外部网络时仍能打开三类预制演示结果。

### 1.3 非目标

首版不实现：

- 多用户、组织和 RBAC。
- 云端仓库任意克隆。
- 自动修改、提交或推送被检视代码。
- 在浏览器内编辑任意完整 Review/Compute Policy YAML。
- 外部 fork PR。
- Web 本地检视的 Finding bypass。
- 通用日志平台或托管 OpenTelemetry 后端。
- 将 Session Insight 作为 Gate 或结果的权威来源。

## 2. 核心设计决定

### W1 — Web、CLI、GitHub 共享应用服务，不通过 Web shell 调用 CLI

新增表面无关的 `ReviewApplicationService`，负责准备输入、创建 Attempt、调用共享 Pipeline、
持久化事件和结果。CLI、Web 和 GitHub Adapter 调用该服务，不允许 Web 后端通过 subprocess
执行 `worktree-review --format json`。

理由：

- 保留 Core 为唯一产品语义来源。
- Web 可以直接消费类型化进度事件，而不需要解析 stderr。
- GitHub worker 可以复用同一个启动与完成路径。
- 避免 CLI 参数或文字输出成为内部 API。

### W2 — 先固定 ReviewEvent，再实现 Web 实时更新和 GitHub worker

所有运行中状态统一表达为版本化、追加式 `ReviewEvent`。Web SSE、Session Journal、结构化
日志和 OpenTelemetry 都消费同一事件，不分别埋点。

### W3 — Web 本地 Attempt 永远非权威

本地 Web 与 CLI 一样，只产生绑定当前 Review Identity 的一次性结果，不改变 GitHub
standing decision，也不能产生 `Passed with bypass`。GitHub Attempt 是否权威由现有
Attempt/CAS 状态决定，Web UI 只展示该状态。

### W4 — Gate 颜色和 Warning 颜色分层

Gate 状态使用绿色、红橙色、深红色、蓝色、灰蓝色和琥珀绿色。黄色只表达非阻断注意
事项，不能伪装成新的 Gate 状态。Blocked 表示已可靠识别的代码风险，Error 表示执行或
完整性失败；二者必须使用不同色相、图标和解释文案。

### W5 — 明暗主题共享语义 Token

组件只能引用语义 Token，例如 `--status-blocked`，不能在组件内硬编码“红色”。明暗主题
分别提供 Token 值，状态含义保持一致。首次访问默认使用深色主题，同时允许选择浅色或
跟随系统；任何主题都不能通过降低正文对比度来追求氛围感。

### W6 — 本地模式使用 SQLite，Session Insight 使用追加式 Journal

本地 Web 使用 SQLite 保存运行索引、配置引用和统计字段；每个 Attempt 同时输出独立、
追加式 Session Journal。SQLite 服务 UI 查询，Journal 服务实时观测与回放，二者职责不同。

### W7 — API Key 不在浏览器持久化或回显

Provider Profile 保存 `${ENV_VAR}` 形式的凭据引用。后端解析凭据，但响应永远不返回真实值。
“保存配置”只做本地验证；“测试连接”是单独、显式、可能产生网络请求的操作。

### W8 — Demo Case 来自真实结果

Passed、Blocked、Error 三类演示数据必须由真实 Pipeline 运行产生，并通过当前结果 Schema
验证。演示页面只回放不可变结果，不手写伪结果。

### W9 — 本地与 GitHub 共用 Review Detail 页面

详情页组件以 `ReviewRunView` 为输入，不直接依赖本地路径或 GitHub PR。平台特有数据放在
来源信息区，不进入 Gate 和 Finding 组件。

### W10 — 默认仅监听 Loopback

本地 Web 默认绑定 `127.0.0.1`，不因提供 UI 而默认暴露到局域网或互联网。远程部署和认证
属于后续独立部署模式。

### W11 — 状态不能仅靠颜色区分

所有 Gate、Finding 严重度、Pipeline 状态和告警必须同时提供文字、图标和颜色，并满足
明暗主题下的可读对比度。

### W12 — Overview 统计必须有明确分母与未知值

Error 不进入 Gate 通过率分母；成本未知不能当作零；GitHub standing decision 与本地一次性
结果必须能分开筛选。

### W13 — Attempt ID 必须在排队和执行前确定

Web 与 GitHub 先创建并持久化 Attempt，再把同一个 `attempt_id` 传给共享 Pipeline。CLI 可以
省略该值并由应用服务分配。任何 Adapter 都不得在数据库、事件流和 Pipeline 中分别生成 ID，
否则无法可靠关联权威状态、Session Journal、SSE 和 GitHub Check。

### W14 — 执行、门禁、权威与发布状态分离

`ReviewRunView` 不使用一个万能 status 字段承载全部生命周期，而是分别表达：

- `run_status`：`queued`、`preparing`、`running`、`completed`、`failed` 或 `interrupted`。
- `gate_state`：`awaiting_review`、`in_progress`、`passed`、`passed_with_bypass`、`blocked` 或
  `error`，与现有 Core/PRD 的 GateState 保持映射。
- `authority`：`local_non_authoritative`、`authoritative`、`superseded` 或 `audit_only`。
- `publication_status`：`not_applicable`、`queued`、`in_progress`、`published` 或 `failed`。
- `bypass_state`：`none`、`active` 或 `invalidated`。

页面上的 Awaiting Review、In Progress、Passed、Blocked、Error 和 Passed with Bypass 是这些字段
的确定性展示投影；例如 `run_status=queued` 显示 Awaiting Review，`authority=superseded` 必须
附加失去权威的说明。Core Pipeline 的 `publish` 阶段表示生成规范结果，不等于 GitHub Check 已
成功发布；远程发布失败也不能改写已经计算出的 Core Gate。

### W15 — Repository 身份与执行路径分离

Repository full name、URL 或稳定 ID 用于来源身份；`repository_path` 只表示经过服务端授权与
重新校验的本地执行位置。GitHub Worker 必须使用受控 mirror/worktree 路径，不能把 Repository
身份字符串当作文件路径，也不能接受 PR 内容指定执行目录。

应用层以 `ReviewExecutionContext` 或等价参数携带 `repository_path`；`ResolvedCommitPair`、
`ReviewRequestKey`、`MergeCandidateIdentity` 继续携带 canonical repository identity。Candidate、
review worktree 和 context 等全部 Git 操作显式接收执行路径，禁止继续隐式执行
`Path(resolved.source_repository)`。

## 3. 逻辑架构

```text
Surfaces
  Local CLI
  Local Web UI
  GitHub Webhook / Check
        │
        ▼
Platform Adapters
  platform.cli
  platform.web
  platform.github
        │
        ▼
ReviewApplicationService
  input preparation
  Attempt lifecycle
  event publication
  result persistence
        │
        ▼
Shared Core Pipeline
  identity → merge → review worktree → context → dimensions
  → verify/dedup → completeness → gate → publish
        │
        ├── ReviewEventBus ──► Web SSE
        │         ├──────────► Session Journal
        │         ├──────────► structlog
        │         └──────────► OpenTelemetry
        │
        └── ReviewReport ────► ReviewRunStore
                                  ├── SQLite local implementation
                                  └── PostgreSQL GitHub implementation
```

### 3.1 模块边界

建议新增的逻辑边界如下；名称表达职责，不要求首个提交一次完成所有模块：

```text
src/worktree_review/
  application/
    review_service.py        # 统一创建和执行 Attempt
    review_events.py         # ReviewEvent 类型和发布协议
    review_runs.py           # ReviewRunStore Protocol
  platform/
    web/
      api.py                 # HTTP DTO 与路由
      sse.py                 # 事件回放和实时订阅
      local_store.py         # 本地 SQLite 实现
      provider_profiles.py   # Provider 连接与凭据引用
      policy_registry.py     # 仓库外可信 Review/Compute Policy
    session_insight/
      journal.py             # Session Journal 写入
      mapping.py             # ReviewEvent 到会话事件映射
  server/
    app.py                   # 组合 Web、GitHub 与健康检查路由
  web/                       # 构建后的静态前端资源或前端工程入口
```

Core 不导入 FastAPI、SQLite、Session Insight 或 GitHub 类型。

## 4. ReviewEvent 契约

### 4.1 事件 Envelope

每个事件至少包含：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `schema` | string | 固定为 `worktree-review.event/v1` |
| `sequence` | integer | Attempt 内从 1 开始、严格递增 |
| `occurred_at` | RFC 3339 string | UTC 发生时间 |
| `attempt_id` | string | Review Attempt ID |
| `surface` | enum | `cli`、`web` 或 `github` |
| `event_type` | string | 下表定义的稳定事件名 |
| `payload` | object | 按事件类型验证的载荷 |

事件顺序由持久化成功的 `sequence` 决定，不使用客户端接收时间决定顺序。重复投递允许，消费
端按 `(attempt_id, sequence)` 去重。

每个 Attempt 由单一有序 Recorder 分配 sequence。Recorder 必须先把事件追加到权威 Store，
持久化成功后再广播给 SSE、Session Journal、结构化日志和 OpenTelemetry 消费者。权威 Event/
Result Store 写入失败必须使应用交付失败；只有 Journal、日志和 OpenTelemetry 等旁路消费者
失败才只形成安全告警，不能回滚已经持久化的 Review 或制造 sequence 空洞。SSE 订阅建立时以持久化水位线
协调“历史回放 + 实时追尾”，保证切换窗口内不漏事件，重复事件仍由 sequence 去重。

### 4.2 首版事件类型

| 事件 | 必需载荷 | 用途 |
| --- | --- | --- |
| `attempt.created` | source、repository display、requested inputs | 建立运行和 Session |
| `inputs.resolved` | target/proposed OID、policy versions | 显示实际检视对象 |
| `stage.started` | stage name | Pipeline 实时进度 |
| `stage.completed` | stage name、elapsed | Pipeline 实时进度 |
| `stage.failed` | stage name、error category、safe detail | 失败关闭与诊断 |
| `dimension.started` | dimension ID | Dimension 实时进度 |
| `dimension.completed` | dimension ID、elapsed、draft count | Dimension 结果 |
| `dimension.failed` | dimension ID、safe detail | Dimension 失败 |
| `provider_call.started` | provider、model、call ordinal | 模型调用观测 |
| `provider_call.completed` | latency、usage kind、tokens、cost | 用量分析 |
| `provider_call.failed` | latency、retryable、safe category | Provider 诊断 |
| `call_plan.ready` | call count、estimated input、output limit | 调用计划披露 |
| `finding.drafted` | fingerprint、severity、dimension | 非证据草稿计数 |
| `finding.verified` | fingerprint、severity、evidence band | 最终 Finding |
| `coverage.recorded` | coverage summary | 完整性展示 |
| `gate.evaluated` | gate state、blocking fingerprints | Gate 展示 |
| `attempt.completed` | terminal state、result reference | 运行终态 |

只有在应用层确实观测到 Provider 调用或 Finding 生命周期边界时，才发出 `provider_call.*`、
`finding.drafted` 或 `finding.verified`。现有 Provider/Pipeline 若尚未暴露可验证钩子，可以先只
记录 Dimension、终态 Finding 和最终 Usage，不能为了动画伪造中间事件。

当前 progress callback 未覆盖 derive-identity、check-completeness、evaluate-gate 和 publish 的
完整 started/completed 边界。实施 ReviewEvent 时应补齐 Core hook；若为兼容旧 Result 只能从
终态 ExecutionRecord 回填，事件 payload 必须标记 `reconstructed: true`，不能用于实时耗时判断。

### 4.3 事件安全规则

默认事件不得包含：

- API Key 或环境变量值。
- 完整 Provider 请求与响应。
- 完整系统提示词。
- 仓库完整源代码。
- 未脱敏的异常对象、HTTP header 或本地 CLI 参数。
- 用户主目录绝对路径，除非只保存在本机且用户明确启用详细路径。

Finding 的 quoted evidence 默认只存于最终本地结果。Session Journal 默认只记录 path、line
range、severity 和 fingerprint；是否复制 quoted evidence 是显式、默认关闭的设置。

## 5. Session Insight 集成

### 5.1 目标

Session Insight 必须能把一次完整 Worktree Review Attempt 展示成可回放 Session，而不只
看到某个 local-cli Provider 创建的零散 Agent 子会话。

### 5.2 Session Journal 目录

默认目录：

```text
$XDG_STATE_HOME/worktree-review/sessions/
  <attempt-id>/
    metadata.json
    events.jsonl
    result.json
```

无 `XDG_STATE_HOME` 时使用平台标准本地状态目录。路径可通过可信服务配置覆盖，但不能从
被检视仓库读取。

`metadata.json` 原子替换，`events.jsonl` 只追加，`result.json` 只在终态后写入并保持不可变。
三类文件分别声明版本：`worktree-review.session-metadata/v1`、`worktree-review.event/v1` 和
`worktree-review.cli.result/v1`；Reader 必须按 schema/version 拒绝或降级处理未知版本。

运行中由 Writer 原子更新 metadata 的 `heartbeat_at` 和 `last_persisted_sequence`，长 Provider
调用期间也维持低频 heartbeat。Writer 重启后从权威 ReviewEvent Store 按 sequence 回补 Journal，
不能因为进程崩溃永久缺失已经持久化的事件。

### 5.3 Session Insight 映射

| Worktree Review | Session Insight 表达 |
| --- | --- |
| Attempt | Session |
| Attempt ID | Session ID |
| Pipeline Stage | Timeline/Tool Event |
| Review Dimension | 子任务或分组 Tool Event |
| Provider Call | 模型调用；可关联 Child Session |
| UsageRecord | Token 与成本分析 |
| Finding | 结构化结果事件 |
| Gate Decision | Session 最终结果 |
| Repository/ref/OID | Session metadata 与 Git evidence |

Session Insight 增加 `worktree-review` Reader，并实现：

- `AgentType`、`DisplayName`、`ListSessions`、`RenderANSI` 等 BaseSessionReader 必需方法。
- `ListSessionsDetailed`：枚举 metadata，报告不完整文件而不误删旧记录。
- `GetSession`：组装 Attempt、阶段、维度、Finding 与 Gate。
- `GetRenderEvents`：把 ReviewEvent 映射为统一回放事件。
- `WatchRoots`：监听 Session Journal 根目录。
- `LiveRevision`：以最后 sequence、文件尺寸或明确 revision 提供轻量实时版本。
- `SessionLive`：根据未终态 metadata 和最近 heartbeat 判断活动状态。
- 注册 Capabilities、Presentation、Reader registry 与 Discover；通过 Reader conformance tests。

稳定深链接格式为 `#/session/worktree-review/<attempt-id>`；若 Session Insight 后续升级路由，必须
通过 capability 版本协商而不是静默拼接新 URL。

### 5.4 子会话关联

当 local-cli Provider 能可靠返回 Codex、Claude 等 Agent Session ID 时，
`provider_call.completed` 记录 `child_agent_type` 和 `child_session_id`。无法可靠取得时保持空值，
不得根据进程时间或模型名称猜测关联。

### 5.5 Web UI 中的 Session Insight 状态

Overview 和 Review Detail 均显示：

- `已连接`：服务可达且支持 Worktree Review Reader。
- `未连接`：Session Insight 未运行或地址未配置。
- `版本不兼容`：服务可达但不支持所需 Reader/深链接能力。
- `观测关闭`：用户关闭 Session Journal。

Session Insight 不可用不能导致 Review Error；它是旁路观测能力。事件写入失败必须记录安全
告警，但不得改变 Gate。

## 6. OpenTelemetry

OpenTelemetry 用于服务级性能观测，不替代 Session Journal。建议的 Span 层级：

```text
review.attempt
  review.prepare_inputs
  review.construct_merge
  review.prepare_review_worktree
  review.gather_context
  review.run_dimensions
    review.dimension.correctness
      review.provider_call
    review.dimension.security
      review.provider_call
  review.verify_dedup
  review.check_completeness
  review.evaluate_gate
  review.publish
```

Span 属性只包含低敏感度结构化字段，例如 surface、stage、dimension、provider、model、status、
token count、cost 和 elapsed。Repository 名称和路径默认散列或省略，不写代码与提示词。

## 7. 视觉设计系统

### 7.1 视觉方向

视觉定位为“精密检视仪器”：专业、严谨、冷静，强调可信、可审计和证据驱动。界面应有
现代开发者工具的精确感，参考 Linear 的层级与克制、Vercel 的排版、Raycast 的紧凑交互、
GitHub Checks 的状态表达和现代可观测性产品的过程呈现，但不直接复制任一产品。

信息密度较高但层级明确，适合长时间使用。第一屏必须直接出现可操作入口、需要开发者采取
行动的 Review 和真实运行状态；统计数据用于辅助判断，不能把产品做成传统 KPI 大屏或营销型
SaaS Dashboard。

### 7.2 主题模式

提供：

- `system`：跟随操作系统。
- `light`：明亮主题。
- `dark`：深色主题。

首次访问默认 `dark`；用户可显式改为 `light` 或 `system`，选择保存在浏览器本地。首屏脚本
必须在绘制前应用已保存主题，避免明暗主题闪烁。深色主题使用深蓝黑或石墨黑而不是纯黑，
浅色主题使用冷白和冷灰，两个主题均保持低眩光和清晰正文对比度。

### 7.3 基础色

| Token | 明亮主题 | 深色主题 | 用途 |
| --- | --- | --- | --- |
| `background` | `#F5F7FB` | `#09111C` | 页面背景 |
| `surface` | `#FFFFFF` | `#101B29` | 卡片和面板 |
| `surface-subtle` | `#EDF1F6` | `#172536` | 次级区域 |
| `text-primary` | `#182231` | `#EEF4FB` | 主文字 |
| `text-secondary` | `#68778B` | `#92A4B9` | 辅助文字 |
| `border` | `#DCE3EC` | `#243448` | 分隔线 |
| `action-primary` | `#315FCB` | `#7094F4` | 克制的蓝紫主操作 |
| `code-background` | `#EEF2F7` | `#0B1522` | 代码、证据和 Hash |
| `focus-ring` | `#1769E0` | `#78A6FF` | 键盘焦点，不与状态色复用 |

### 7.4 状态色

| 状态 | 明亮主题 | 深色主题 | 文字含义 | 图标 |
| --- | --- | --- | --- | --- |
| Passed | `#168557` | `#45CF8B` | 检视完成并允许通过 | 圆形勾 |
| Passed with Bypass | `#747B24` | `#BDC75D` | 已授权接受风险，并非完全安全 | 盾牌与风险标记 |
| Blocked | `#D84A32` | `#FF755F` | 检视完成，发现阻断风险 | 八边形叉号 |
| Error | `#C52345` | `#FF5C7A` | 检视未完成，结论未知 | 断裂流程/圆形叉号 |
| Warning | `#A67C00` | `#F0CA45` | 非阻断注意事项 | 三角告警 |
| Running | `#1769E0` | `#72AAFF` | 正在执行 | 动态圆点 |
| Awaiting | `#68778B` | `#92A4B9` | 排队或尚未启动 | 时钟 |

红色、红橙色、琥珀绿色和黄色的边界：

- 红橙色：代码风险已被可靠识别，Gate 明确 Blocked。
- 深红色：执行或完整性失败，无法得出可靠代码结论。
- 琥珀绿色：授权界面接受了已知阻断风险，保留警示感，不能表现成普通 Passed。
- 黄色：结论仍有效，但存在非阻断 Finding、预算接近上限或可选上下文缺失。

### 7.5 Finding 严重度

| 严重度 | 色彩 | 说明 |
| --- | --- | --- |
| Critical | 深红色 | 最高风险，通常阻断 |
| Major | 红橙色 | 重大问题，默认策略通常阻断 |
| Minor | 黄色 | 需要关注但默认不阻断 |
| Suggestion | 蓝色 | 改进建议 |

Gate 与 Finding 使用不同图标、标签形状和解释文案，避免 Critical 与 Error、Major 与 Blocked
因色彩接近而被误读。

### 7.6 字体、间距与组件

- UI 字体：Geist、Inter 或等价的中英文可读无衬线字体。
- 等宽字体：Geist Mono、JetBrains Mono 或系统等宽字体。
- 正文：15–16px。
- 常用标签和表格：至少 14px。
- 辅助 metadata：12–13px。
- 页面使用 12 列模块化网格；内容可跨列组合，不强迫每个区块等宽或等高。
- 基础间距单位：8px。
- 面板和控件圆角：8–12px，避免过度圆润。
- Button、Input、Select 最小高度：36px。
- 交互目标最小尺寸：40×40px；紧凑桌面表格例外需提供足够行高。
- Repository、文件、Policy、Provider 和 Attempt 使用一致且克制的图标体系。
- 路径、代码、SHA、Fingerprint 和机器标识使用等宽字体与 tabular numbers。

### 7.7 表面、边界与页面构图

- 使用细冷灰边框、背景层次和间距建立结构，避免依赖大面积阴影。
- 常驻页面表面原则上无阴影；Dialog、Popover、Command Palette 等浮层可以使用低强度阴影。
- 不为每个内容块单独套卡片。相关信息优先共享一个表面，并用标题、分隔线和网格组织。
- Gate、需要采取行动的 Review 和失败节点可以获得更强边框或色带，但不使用整块高饱和背景。
- 代码与 Evidence 区采用独立的低眩光表面，并保持行号、引用行和来源信息的清晰层级。
- Dashboard 首先显示需要处理的 Reviews 和活跃运行，统计趋势位于第二视觉层级。
- 页面留白充足但紧凑，确保 1280px 和 1440px 桌面视口同时具备合理信息密度。

### 7.8 明确禁止的视觉模式

不得使用：

- 大面积玻璃拟态或透明模糊面板。
- 巨型渐变标题、霓虹光球和漂浮装饰物。
- 装饰性 3D 图形。
- 机器人、魔法棒、AI 星光等通用 AI 隐喻。
- 每个区块都使用独立卡片的普通企业后台模板。
- 低对比度正文或仅靠颜色传达状态。
- Critical、Major、Blocked 或 Error 的持续闪烁。
- Passed 状态的彩纸、烟花或其他庆祝动画。

### 7.9 动效规范

动效只解释层级、状态变化和检视进程，不作为装饰。

页面进入：

- 主内容轻微上移并渐显。
- 不同信息区块以 40–70ms 间隔错峰出现。
- 首屏整体进入在 500ms 内完成。

Pipeline：

- 当前阶段的节点和连接线显示缓慢、低亮度的数据流或脉冲。
- 阶段完成后自然转换为完成标记；失败后停止数据流并展开安全错误原因。
- Finding 出现时，对应 Dimension 节点只做一次短暂提示，不持续闪烁。
- Gate 只在 Required Dimensions 和 Coverage 检查完成后出现。
- 不使用无限旋转的大型 Loading Indicator。

Finding 与 Evidence：

- 筛选使用 layout transition，保持选中 Finding 的位置可理解。
- Finding 展开时平滑调整高度。
- 切换 Finding 时，Evidence 使用快速淡入并将引用行滚动到可视区域。
- Hover 只改变边框、背景或最多 1–2px 的轻微位移。

Gate：

- Passed 使用简短描边完成动画，不播放庆祝效果。
- Blocked 快速收紧状态区域并呈现 blocking reasons。
- Error 定位失败节点并展示恢复建议。
- Passed with Bypass 的转换必须保留风险感，不能复用普通 Passed 动画。

Attempt：

- 新 Attempt 从时间轴顶部进入。
- 原 Authoritative Attempt 平滑弱化为 Superseded。
- Standing Decision 撤销必须通过状态和文案明确可见。
- Elapsed、Token 和 Cost 数值允许平滑更新，但不得为了动画延迟真实状态。

时间建议：

| 动效 | 时长 |
| --- | --- |
| Hover | 120–180ms |
| 控件反馈 | 100–160ms |
| 内容切换 | 180–260ms |
| Dialog/Drawer | 220–320ms |
| Pipeline 状态变化 | 300–500ms |

默认使用 `ease-out`、`ease-in-out` 或克制的 spring，避免明显弹跳、果冻效果、长时间视差。
`prefers-reduced-motion` 下移除位移、光流和 spring，只保留必要的即时状态更新或短淡入。

### 7.10 前端技术栈与原型模式

目标 Web UI 使用：

- React 与 TypeScript。
- Tailwind CSS 和集中管理的语义化设计 Token。
- Framer Motion，仅用于布局切换、Dialog、时间轴和 Pipeline 状态变化。
- Lucide Icons，所有图标必须有领域含义和可访问名称。
- Recharts，仅用于 Gate、Token 和 Cost 等确实需要图形表达的趋势。

前端放在独立 `frontend/` 工程，生产构建物由 FastAPI 服务。开发时允许独立前端 Dev Server。
9 月 10 日的 Phase 0 离线原型可使用绑定 `127.0.0.1` 的 Vite Preview；“单 FastAPI 进程、不要求
Node”从本地 Web MVP 起成为强制验收条件。两种启动方式的运行时都不得访问外网。

前端通过 `ReviewDataSource` 边界切换两种数据源：

- `mock`：高保真交互原型使用的 schema-valid 数据，页面持续显示 `Mock data` 标识。
- `live`：通过 `/api/v1` 和 SSE 访问真实 ReviewApplicationService。

Mock 模式不得污染生产运行历史。正式演示的 Passed、Blocked、Error Case 仍使用真实 Pipeline
生成的不可变快照，而不是手写 mock。

## 8. 信息架构

```text
总览 Overview
Reviews
  Review Detail
    Overview
    Findings
    Coverage
    Attempts
    Identity & Provenance
    Policies
    Usage
Repositories
Policies
  Review Policies
  Compute Policies
Providers
集成 Integrations
  Session Insight
  GitHub
Audit Log
系统设置 Settings
```

“发起检视”是全局主操作，不占用固定导航项。Demo Cases 只在演示或开发模式显示，不作为生产
主导航。首版 Policies 页面为只读登记和检查，不提供任意 YAML 编辑器。

`Reviews` 是面向用户的统一概念：列表按 Review Request 和来源组织，内部可包含一个或多个
Attempt。旧名称 `Runs` 不再作为主导航名称，但 API 和 Store 仍可以使用明确的
`ReviewRun` 技术术语。

Audit Log 在本地 MVP 隐藏；GitHub 权威发布启用后显示。它只记录 retry、authority、
publication、bypass 和授权等审计事件，不混入普通服务日志。

## 9. 全局页面框架

桌面端使用固定左侧导航和可滚动主工作区：

```text
┌───────────────┬──────────────────────────────────────────────────┐
│ Product       │ Repository | Search | Provider | Theme | Menu   │
│               ├──────────────────────────────────────────────────┤
│ Navigation    │                                                  │
│               │ Main content                                     │
│ Integrations  │                                                  │
│               │                                                  │
│ Service state │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```

导航底部持续显示：

- Web 服务健康状态。
- 当前版本。
- 当前运行模式：Local 或 Server。
- Session Insight 连接简态。

顶部全局区域包含：

- Repository Switcher：切换已登记 Repository，并改变页面过滤上下文。
- Global Search：目标产品用于搜索 Review、Attempt、Finding fingerprint 和 path；本地 MVP 可
  先只支持 Review/Attempt metadata，并在能力不可用时隐藏而不是展示空壳。
- Provider Status：显示 `Healthy at <time>`、`Last call failed` 或 `Not tested`，不得把历史成功
  冒充实时 Live 状态。
- Theme Switcher：Dark、Light、System。
- Environment/User Menu：Local 模式显示运行环境和设置；只有启用认证的部署才显示用户菜单。
- `New Review`：始终作为顶部主操作。

## 10. Overview 页面

### 10.1 页面目标

用户进入产品后，在一个屏幕内回答：

1. 当前有哪些 Review 需要我采取行动？
2. 是否有正在运行、Blocked、Error 或等待处理的 Review？
3. 问题主要集中在哪些严重度或维度？
4. 模型用量与成本是否正常？
5. Session Insight 是否正在观测？

首屏视觉顺序固定为：需要关注的 Review、活跃 Review、近期 Review、统计摘要和趋势。指标不得
占据第一视觉层级，也不得把 Overview 做成传统 KPI 大屏。

### 10.2 全局过滤器

- 时间：7 天、30 天、90 天、全部。
- Repository。
- Surface：Local Web、GitHub；只有实现并启用 CLI Result 导入 capability 后才显示 CLI Import。
- Provider/Model。

过滤条件写入 URL query，刷新和分享页面时保持一致。Local 模式下只在本机使用该 URL。

### 10.3 核心指标

| 指标 | 定义 |
| --- | --- |
| 检视次数 | 过滤范围内创建的 Attempt 数 |
| Gate 通过率 | `Passed / (Passed + Blocked)`；排除 Error |
| Blocked 次数 | 终态为 Blocked 的 Attempt 数 |
| Error 率 | `Error / 所有终态 Attempt` |
| 平均耗时 | 所有终态 Attempt 从 created 到 completed 的平均值 |
| 模型成本 | 已知成本之和，并同时显示未知成本记录数 |

辅助指标可以包含 p50/p95 耗时、平均 Findings/Attempt、输入输出 Token 和预算拒绝次数。

### 10.4 图表和卡片

Overview 首版包含：

1. Attention Queue：Blocked、Error、Awaiting Review 和需要授权操作的 Review。
2. Active Reviews：Pipeline、Dimension、elapsed、Provider 和模型调用实时状态。
3. Recent Reviews：Repository、Source、Gate、Finding、Duration、Model、Time。
4. Gate 摘要与趋势：按日/周堆叠 Passed、Blocked、Error 和 In Progress。
5. Finding 严重度：Critical、Major、Minor、Suggestion 横向条形图。
6. Dimension 健康度：完成率、失败率和平均耗时。
7. 模型用量：输入 Token、输出 Token、成本和未知计量。
8. Review Policy 使用情况：Policy 版本的 Review 数、Blocked 数和 Error 数。
9. Provider 健康状态：最后测试或最后调用结果及其时间。
10. Session Insight：连接状态、当前 Attempt、可用 Child Session 数和跳转入口。

### 10.5 页面结构原型

```text
┌───────────────┬────────────────────────────────────────────────────────────┐
│ Worktree      │ Repository⌄  Search  Provider  ◐ Theme   + New Review     │
│ Review        │                                                            │
│               │ 需要关注 · 3                                                │
│ ● Overview    │ ┌────────────────────────────────────────────────────────┐ │
│ ◇ Reviews     │ │ BLOCKED  payment-service #184      1 blocking finding │ │
│ ◇ Repositories│ │ ERROR    demo-invalid-config       merge not built     │ │
│ ◇ Policies    │ └────────────────────────────────────────────────────────┘ │
│ ◇ Providers   │                                                            │
│               │ ┌───────────────────────────────────┐ ┌────────────────┐ │
│ Integrations  │ │ 正在检视 worktree-review          │ │ Session Insight│ │
│ ● Session     │ │ ✓ Merge ✓ Worktree ◉ Security    │ │ ● 已连接       │ │
│ ○ GitHub      │ │ correctness 完成 · 01:24          │ │ 6 child sessions│ │
│               │ └───────────────────────────────────┘ └────────────────┘ │
│ Audit Log     │                                                            │
│ Settings      │ 最近检视                                                   │
│               │ payment-service  Blocked  2 findings  2m18s  刚刚         │
│               │ session-insight  Passed   0 findings  2m11s  14:32        │
│               │                                                            │
│               │ [检视 24] [通过率 70.8%] [Error 12.5%] [成本 $3.84]        │
│               │ [Gate 趋势] [Finding 严重度] [Policy 使用] [Provider 状态] │
└───────────────┴────────────────────────────────────────────────────────────┘
```

## 11. 发起检视页面

页面采用分区表单，不使用多步向导隐藏关键上下文。用户在点击开始前应能同时看见仓库、来源、
Policy、Model 和传输披露。

### 11.1 Repository 区

- 已授权 Repository 选择器。
- “添加本地 Repository”操作。
- Repository Root。
- 当前 Branch。
- Worktree 是否有修改。
- 已跟踪修改和未跟踪文件数量。
- Git 版本与 Repository 校验状态。

浏览器不能直接枚举整个文件系统。后端只接受用户明确登记并解析后的 Repository Root，避免
恶意网页请求任意本地路径。

### 11.2 Review Source 区

互斥选项：

- 当前 Worktree。
- 最近 N 次提交加当前 Worktree。
- 显式 committed ref。

字段显示规则：

| 模式 | Target | Commits | Proposed |
| --- | --- | --- | --- |
| Current Worktree | 可选，默认 HEAD | 隐藏 | 固定 WORKTREE |
| Recent Commits | 由 `HEAD~N` 派生 | 必填，N ≥ 0 | 固定 WORKTREE |
| Committed Ref | 可选 | 隐藏 | 必填；Worktree 必须 clean |

### 11.3 Review Policy 区

- 内置默认 Policy。
- 已登记外部 Policy。
- Semver 和 SHA-256。
- Required Dimensions。
- Blocking Severities 与最低证据等级摘要。
- 只读查看 Policy 内容。

任何外部 Policy 必须位于被检视仓库之外。

### 11.4 Compute Policy 与 Provider Profile 区

展示：

- Compute Policy 名称、版本与 Model。
- Provider Profile 名称、Provider、Endpoint 或 Local Command destination。
- Credential 环境变量引用状态。
- 单次最大输出 Token。
- 最大预算。
- 数据目的地与已知保留策略。
- Provider Configuration Fingerprint（local-cli 时）。

### 11.5 启动确认区

开始按钮上方固定展示：

- 实际 Repository。
- Target 与 Proposed 选择。
- Provider/Model。
- 数据发送目的地。
- 已知保留策略。
- Review/Compute Policy 版本。
- 预算和最大模型调用输出。

点击“开始检视”后返回 Attempt ID 并立即进入 Review Detail。重复点击由 idempotency key 防止创建
重复 Attempt。

### 11.6 Repositories 页面

Repositories 页面负责本地路径授权和 GitHub Repository 可见性，不负责修改 Repository 内容。

本地 Repository 显示：

- Display name 和 canonical root。
- 当前 branch、HEAD 和 dirty state。
- 最近 Review、最后 Gate 和最后运行时间。
- 是否仍可访问、是否发生 identity/path 漂移。
- 移除授权操作；该操作不删除磁盘内容或历史 Review。

GitHub Repository 在基础集成完成后显示：

- Full name、installation 和默认分支。
- App 权限与 webhook 状态。
- 最近 PR Review 和 Check 发布状态。

## 12. Providers 与 Compute Policies 页面

### 12.1 列表

Provider Profile 只描述连接能力。每个 Profile 显示：

- Name。
- Provider。
- Endpoint 或 local-cli adapter。
- Credential 状态：Configured、Missing、Invalid reference。
- 最近使用时间。
- 最近健康状态与探测时间。

### 12.2 编辑字段

Remote Provider：

- Name。
- Provider：Anthropic 或 OpenAI。
- Optional URL。
- Credential reference，例如 `${OPENAI_API_KEY}`。

Local CLI：

- Name。
- Command argv；不经过 shell。
- Adapter。
- Optional adapter label。

Model、Max output tokens、Budget、Pricing、Data destination、Known retention 和 Provider handoff
属于 Compute Policy，不能在 Provider Profile 中复制一套可漂移配置。

### 12.3 操作语义

- 保存：只验证 Schema、路径和可执行文件存在性，不调用模型。
- 测试连接：明确提示会产生一次外部或 local-cli 调用。
- 删除：若被历史 Attempt 引用，只删除可选 Profile，不删除历史配置快照。
- 设为默认连接：只影响之后新建的 Compute Policy 或 Attempt 解析。

### 12.4 Policies 页面

Policies 使用两个语义分离的子页面：

Review Policies：

- Required Dimensions。
- Blocking Severities。
- Minimum Blocking Evidence Band。
- Context Rules。
- Mandatory、Optional 与 Excluded Globs。
- Output Language。
- Policy Version 和 SHA-256。

Compute Policies：

- Provider 与 Model。
- Maximum Output Tokens per Call。
- Review Budget。
- Pricing Source 和不确定价格启动规则。
- Data Destination。
- Known Retention。
- Policy Version 和 SHA-256。

页面固定说明：Review Policy 决定检视与 Gate；Compute Policy 决定模型、预算和调用限制。
Policy 必须来自被检视 Repository 之外的可信位置。Repository 内的指令、评论和文档均是不可信
上下文，不能修改 Gate 规则。

## 13. Review Detail 页面

### 13.1 信息优先级

Gate、Review Source、候选身份摘要和当前 Attempt 固定在标签页上方。来源信息自适应：

- GitHub：Repository、PR number/title、Author、proposed branch、target branch、commit SHA、
  Authoritative Attempt 和 Check 链接。
- Local Web/CLI：Repository、Worktree/ref、target、snapshot SHA 和 `Local one-shot result`；不显示
  PR、Author 或 Standing Decision。

共享信息从上到下固定为：

1. Gate 和 Summary。
2. Review Source 与当前 Attempt。
3. 合并候选检视路径。
4. Detail Tabs。

Detail Tabs 固定为：Overview、Findings、Coverage、Attempts、Identity & Provenance、Policies、
Usage。页面刷新和直接链接必须保留当前 Tab；Finding 选择和筛选使用 URL query 或 fragment
表达。

### 13.2 页面结构原型

```text
┌────────────────────────────────────────────────────────────────────────┐
│ acme/payment-service · PR #184                         BLOCKED         │
│ Harden webhook authorization · feature/webhook-auth → main            │
│ Author · SHA · Policy 1.3.0 · attempt_01JY8R7F2W · 2m18s · $0.42     │
├────────────────────────────────────────────────────────────────────────┤
│ Target + Proposed → Merge Tree → Review Worktree → Context → Dimensions│
│        → Evidence Verification → Gate                                  │
├────────────────────────────────────────────────────────────────────────┤
│ Overview | Findings | Coverage | Attempts | Identity | Policies | Usage│
├───────────────────────┬────────────────────────────────────────────────┤
│ Findings              │ MAJOR · SUPPORTED · correctness               │
│                       │                                                │
│ ● Major  1            │ 问题陈述                                       │
│ ● Minor  1            │ 模型验证后的具体问题                           │
│                       │                                                │
│ Dimensions            │ 影响                                           │
│ ✓ correctness         │ 对候选合并树产生的预期影响                     │
│ ✓ security            │                                                │
│ ✓ architecture        │ 证据                                           │
│                       │ src/module.py:42–47                             │
│ Coverage              │ ┌────────────────────────────────────────────┐ │
│ 48 reviewed           │ │ 42  verified source text                 │ │
│ 2 excluded            │ │ 43  tied to immutable snapshot           │ │
│ 0 missing             │ └────────────────────────────────────────────┘ │
│                       │                                                │
│ Usage                 │ 修复建议                                       │
│ 32.8k / 4.2k tokens   │ 明确、非自动应用的修复方向                     │
└───────────────────────┴────────────────────────────────────────────────┘
```

### 13.3 合并候选检视路径

顶部用简洁节点和连接线表达：

```text
Target Head + Proposed Head
    → Exact Merge Tree
    → Read-only Review Worktree
    → Context
    → Review Dimensions
    → Evidence Verification
    → Gate Decision
```

该路径强调被检视的是精确 Merge Result，而不是单独 diff。它是领域解释，不替代 Overview Tab
中的九阶段 Pipeline。当前节点显示克制脉冲，已完成节点显示完成标记，失败节点停止数据流并
展开安全原因，未开始节点弱化。Merge Tree 构造失败时路径在该节点终止；Gate 只在 Required
Dimensions 和 Coverage 检查结束后出现。

### 13.4 Overview Tab

首先展示 Gate Decision、Blocking Findings、Required Coverage、Estimated/Actual Cost 四个摘要，
随后展示 Review Summary、Required Dimensions、九阶段 Pipeline、Finding 严重度、Coverage、
Provider/Model、Data Destination 和 Retention Disclosure。

Dimension ID 由实际 Review Policy 动态提供，不把六个示例维度硬编码为枚举。每个 Dimension
显示 completed、failed 或 not-started，以及 elapsed、Finding 数和 blocking Finding 数。

### 13.5 Findings Tab

桌面端使用 Master-detail 工作区：1280px 使用列表/详情双栏，1440px 以上可使用筛选、列表、
详情三栏；平板和移动端转换为保留选择状态的堆叠导航。

左侧提供 Problem/path/fingerprint 搜索、Severity、Dimension、Evidence Band、Path 筛选和
`Blocking only` 开关。筛选只改变当前视图，不改变 Gate。

每个 Finding 显示：

- Severity。
- Evidence Band。
- Dimension。
- Problem Statement。
- Expected Impact。
- Repair Guidance。
- 一个或多个 Evidence Span。
- Fingerprint 的短格式和复制入口。
- GitHub 模式下的 annotation 状态与 bypass 状态。

Evidence Span 显示 path、start/end line、source、snapshot identity、change kind 和 verified quoted
text。Evidence Viewer 提供语法高亮和行号，并用非纯颜色方式强调引用行。切换 Finding 时滚动到
相关代码行。删除文件的证据使用 Target Tree 或 Merge Diff 表达，不伪装为 Review Worktree
文件。产品不提供一键自动修改、提交或推送按钮。

### 13.6 Coverage Tab

顶部显示 `Required Coverage: Complete/Incomplete`，分段覆盖条或环形图只作为摘要，不能用
模糊百分比掩盖缺失内容。

文件树按 Reviewed、Mandatory Missing、Optional Missing、Excluded、Unreviewable 分组。每个
非 Reviewed 项显示原因、来源规则和影响。Mandatory 内容缺失、changed content 无法检视或
Required Dimension 未完成时，页面解释 Gate 为 Error 的原因，并链接到失败 Stage/Dimension。

现有 Core `CoverageRecord` 只有分类 path tuple，实施时需增加稳定的 View 投影或向后兼容的
Core 字段来携带 reason/rule。底层未记录时必须显示 `Reason not reported by this result schema`，
不能根据文件名或数组位置猜测。

### 13.7 Attempts Tab

按 Review Request 展示时间轴。每个 Attempt 显示 Attempt ID、Authority/Superseded、Gate、
Trigger、Provider/Model、Review/Compute Policy 版本、Token、Cost、Started 和 Duration。

GitHub 当前 Authoritative Attempt 明显突出；Superseded Attempt 固定说明它已不能发布或覆盖
Standing Decision。Retry 前必须确认并显示：

> Retry will create a new authoritative attempt and temporarily revoke the current standing
> decision until the review completes.

确认后 GitHub Standing Decision 进入 Awaiting Review，新 Attempt 成为 Authoritative，原 Attempt
转为 Superseded，Pipeline 从第一阶段开始。本地 Retry 也创建新 Attempt，但不显示权威转移。

### 13.8 Identity & Provenance Tab

展示 Review Request Key、Source Repository、Target Ref/Head OID、Proposed Source/Head OID、
Merge Tree OID、Review Identity、Review/Compute Policy version/SHA-256 和 Attempt ID。Hash 使用
可复制等宽文本，默认截断，Focus/Hover 可查看完整值。

```text
Review Request Key ──► 系统被要求检视什么
        │
        └─ merge constructed ─► Review Identity ──► 结论适用于什么

Attempt ──► 哪次执行产生结果
        └─ authoritative and current ─► Standing Decision
```

Merge Tree 构造失败时固定显示：

> Review identity unavailable — merge candidate was not constructed.

不得创建空 OID、占位 SHA 或伪 Review Identity。

### 13.9 Policies Tab

显示本次 Attempt 实际使用的 Review Policy 和 Compute Policy 快照，而不是当前已更新的 Profile。
内容与 Policies 页面一致，并额外显示版本 SHA、Data Destination、Retention Disclosure 和
Provider Configuration Fingerprint。

### 13.10 Usage Tab

展示 Call Plan、每次 Provider Call 的模型/elapsed/usage kind/input/output token/cost、Estimated
与 Actual 分离的总计、Unknown 的原因，以及 Budget limit、已用比例和 Budget exhausted 位置。
图表必须同时提供可读数值或表格。

现有 `UsageRecord` 未携带 dimension、call ordinal 和 elapsed；Live 实现需要通过可验证的调用
hook 增加这些关联，或明确显示 unknown/not reported。UI 不得把 tuple 顺序冒充调用身份或耗时。

### 13.11 Bypass Interaction

只在 GitHub 授权界面、完整检视结束且存在 blocking Finding 时显示。Bypass 是逐 Finding 操作，
不是对整个 Error 或未知风险的一键通过。

确认 Dialog 要求非空原因，展示风险、Finding Fingerprint、当前 Review Identity 和失效条件，
并固定显示：

> Bypass means accepting the risk. It does not mean the finding was resolved.

Error 不能 Bypass。Bypass 成功后保留原 Finding、授权原因、授权者和审计记录，并呈现 Passed
with Bypass，不能表现成普通 Passed。

### 13.12 Error 页面状态

Error 不是空白错误页。必须显示：

- `Gate: Error`。
- 安全错误摘要。
- 失败 Stage/Dimension。
- 已完成和未开始的阶段。
- 是否构造出 Review Identity。
- Draft Findings 与“未经验证、不是证据”的说明。
- Retry 操作；本地 Retry 创建新 Attempt，GitHub Retry 遵守权威状态。

## 14. Reviews 页面

### 14.1 字段

- Repository。
- Source 类型与 Target/Proposed。
- Surface。
- Gate。
- Findings 数量与最高严重度。
- Provider/Model。
- Duration。
- Cost 或 Unknown。
- Created/Completed time。
- GitHub authoritative/superseded 状态。

### 14.2 筛选

- 时间范围。
- Repository。
- Gate。
- Surface。
- Severity。
- Provider/Model。
- Authoritative/Superseded。

### 14.3 操作

- 打开详情。
- 导出版本化 JSON。
- 对同一表面重新发起新 Attempt。
- 打开 Session Insight。

运行结果不可在 UI 中编辑。首版不提供删除历史结果；后续如增加删除，必须同时定义 Session
Journal 和统计索引的一致性语义。

### 14.4 Audit Log

Audit Log 只在存在可审计平台状态时启用，至少包含：

- Authoritative Attempt 变更。
- Standing Decision 撤销和发布。
- Retry 请求、操作者、原因和结果。
- Bypass 请求、Finding Fingerprint、Review Identity、操作者、原因和失效。
- GitHub webhook delivery 和幂等重放结果。
- 授权成功、拒绝和策略版本变更。

Audit Event 必须有时间、事件类型、Actor、Attempt/Review Request 关联和安全 payload。普通 HTTP
访问日志、调试日志和异常堆栈不进入 Audit Log。

## 15. Demo Cases 页面

预置三类 Case：

| Case | 必需特征 |
| --- | --- |
| Passed | required dimensions/coverage 完整，无 blocking Finding |
| Blocked | 至少一个已验证、达到 Policy 阻断条件的 Finding |
| Error | 明确失败 Stage，不产生伪造 Review Identity 或 Passed |

每个 Case 提供：

- 打开稳定快照。
- 在轻量示例 Repository 上重新执行。
- 结果生成时间。
- Result Schema 版本。
- Review/Compute Policy 版本。
- 是否需要模型或网络。

快照展示不依赖模型、Provider、GitHub 或 Session Insight 运行状态。

### 15.1 高保真原型示例

交互原型使用清楚标记为 `Mock data · Pre-Alpha` 的 schema-aligned 示例：

- Repository：`acme/payment-service`。
- PR：`#184 Harden webhook authorization`。
- Proposed/Target：`feature/webhook-auth → main`。
- Gate：Blocked。
- Authoritative Attempt：`attempt_01JY8R7F2W`。
- Review Policy：`1.3.0`。
- Provider/Model：`openai / gpt-5.6`。
- Required Coverage：Complete。
- Cost/Duration：`$0.42 / 2m 18s`。

示例 Findings：

1. Major/Supported/Security，`src/webhooks/verify.py:74`：缺失签名 Header 时 fallback 分支仍接受请求。
2. Minor/Supported/Maintainability，`src/config/provider.py:118`：Retention Disclosure 在两条配置路径重复。
3. Suggestion/Insufficient/Architecture，`src/server/app.py:42`：建议把 GitHub transport mapping 移出服务入口。

这些数据用于目标交互原型，不暗示远程 Provider、Session Insight Reader、GitHub 授权或 Check
发布已经端到端可用。Production bundle 不加载手写 mock；正式演示快照来自真实 Pipeline。

## 16. Web API

所有 API 位于 `/api/v1`。错误响应使用稳定 error code 和安全 detail，不把异常堆栈返回浏览器。

API 输出使用面向 Surface 的 `ReviewRunView`，它组合 Core ReviewReport 与平台元数据。Local 与
GitHub 字段使用 discriminated union；PR、Author、Authority 和 Trigger 不反向写入 Core
ReviewReport。Estimated Cost 必须标记为估算来源，不能冒充实际 Usage。

### 16.1 Review API

| 方法与路径 | 返回 | 说明 |
| --- | --- | --- |
| `POST /api/v1/reviews` | `202` + Attempt locator | 创建 Attempt |
| `GET /api/v1/reviews` | 分页 Run summary | 查询历史 |
| `GET /api/v1/reviews/{attempt_id}` | Run detail | 当前快照或终态结果 |
| `GET /api/v1/reviews/{attempt_id}/events` | SSE | 回放后实时追尾事件 |
| `GET /api/v1/reviews/{attempt_id}/result` | Versioned result | 有 ReviewReport 的终态可用；否则 `409 result_unavailable` |
| `POST /api/v1/reviews/{attempt_id}/retry` | `202` + new Attempt | 创建新 Attempt |
| `POST /api/v1/reviews/{attempt_id}/findings/{fingerprint}/bypass` | Updated standing view | P3；GitHub 授权与非空理由必需 |

`POST /reviews` 的 source 是 discriminated union：

- `local-worktree`
- `local-recent-commits`
- `local-committed-ref`
- `github-pull-request`

Retry/Bypass endpoint 在本机单用户 P0/P1 不代表 GitHub 授权。GitHub P2 的 Retry 首先由 Checks
requested action 触发；Web Retry/Bypass 只有在部署认证可可靠映射 GitHub actor 后才启用。

创建与 Retry API 接受 `Idempotency-Key`。同一 key、同一规范化请求在有效期内返回原 Attempt；
同一 key 被用于不同请求时返回稳定的 conflict error。服务必须在返回 `202` 和加入后台队列前
持久化 Attempt、权威关系及首个事件，避免浏览器已获得 locator 但运行不可查询。GitHub webhook
使用 delivery/request identity 生成稳定幂等键，重复投递不得创建并列权威 Attempt。

### 16.2 Repository API

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/v1/repositories` | 已授权本地 Repository |
| `POST /api/v1/repositories` | 登记和校验 Repository Root |
| `GET /api/v1/repositories/{id}/status` | Branch、dirty state、refs 摘要 |
| `DELETE /api/v1/repositories/{id}` | 移除授权，不删除 Repository |

### 16.3 Provider Profile 与 Policy API

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/v1/provider-profiles` | 返回脱敏的 Provider 连接列表 |
| `POST /api/v1/provider-profiles` | 创建 Provider Profile |
| `PATCH /api/v1/provider-profiles/{id}` | 更新 Provider Profile |
| `DELETE /api/v1/provider-profiles/{id}` | 删除可选 Profile |
| `POST /api/v1/provider-profiles/{id}/test` | 显式测试 Provider 连接 |
| `GET /api/v1/review-policies` | 列出可信 Review Policy 摘要 |
| `GET /api/v1/review-policies/{id}` | 查看 Review Policy 和版本身份 |
| `GET /api/v1/compute-policies` | 列出可信 Compute Policy 摘要 |
| `GET /api/v1/compute-policies/{id}` | 查看 Compute Policy、Provider Profile 引用和版本身份 |

### 16.4 Overview 与 Integration API

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/v1/overview` | 聚合指标、趋势和活跃运行 |
| `GET /api/v1/integrations/session-insight` | 连接与能力状态 |
| `PUT /api/v1/integrations/session-insight` | 更新可信地址与开关 |
| `GET /api/v1/integrations/github` | GitHub App 配置和 worker 状态 |
| `GET /api/v1/audit-events` | 分页查询平台审计事件；本地 MVP 可返回 capability unavailable |

### 16.5 SSE 行为

- Client 可以通过 `Last-Event-ID` 或 query sequence 断线续传。
- 服务通过订阅水位线协调 Store 回放和内存事件总线；实现可以先订阅再回放并按 sequence 去重，
  或使用等价的原子快照机制，但不能在“回放结束、开始订阅”之间丢事件。
- SSE `id` 等于 ReviewEvent sequence。
- 每 15 秒发送不带业务语义的 heartbeat。
- `attempt.completed` 后服务关闭该 Attempt 的事件流。
- 慢客户端不能阻塞 Pipeline；超出缓冲区时断开，由客户端按 sequence 重连。

## 17. 数据与持久化

### 17.1 ReviewRunStore Protocol

存储接口至少支持：

- 在同一事务内创建 Attempt、登记 idempotency request digest/authority，并写入首个事件。
- 追加 ReviewEvent。
- 更新运行状态。
- 写入不可变 ReviewReport。
- 按 Attempt ID 查询。
- 分页和筛选运行。
- 计算 Overview 聚合。
- 标记中断运行。

建议把首项定义为 `create_attempt_with_initial_event_and_idempotency(...)`，避免 API 在分离的
create/append 之间崩溃后留下没有首事件的 Attempt。Input preparation failure 或 interrupted
运行可能没有 ReviewReport；错误详情仍由 ReviewRunView 提供，Result endpoint 返回稳定的
`result_unavailable`，不能合成伪 Report。

### 17.2 本地 SQLite

建议逻辑表：

- `repositories`
- `provider_profiles`
- `trusted_review_policies`
- `trusted_compute_policies`
- `review_runs`
- `review_events`
- `review_results`
- `idempotency_records`
- `integration_settings`

Finding、Coverage 和 Usage 可以在终态保存规范 JSON，同时将常用筛选字段投影到 `review_runs`
或专用索引表。规范结果 JSON 是最终事实，统计投影可重建。

### 17.3 PostgreSQL GitHub 模式

复用现有 authoritative Attempt Store，并扩展 Review Result/Event 查询。GitHub standing decision
仍只由 CAS 发布路径修改，Web 查询或 SSE 不参与权威决定。

### 17.4 不可变性

- Attempt ID 不变。
- Review Report 终态后不可覆盖。
- Retry 总是创建新 Attempt。
- Provider Profile 更新不改写历史 Compute Policy 或 Provider Configuration Snapshot。
- Demo Case 通过 Result Schema 版本固定。

## 18. 后台执行模型

首版本地 Web 在单进程中使用受控 async worker：

- 默认最大并发：1。
- 可配置但有安全上限。
- 创建 Attempt 并持久化后才加入队列。
- Pipeline 不能在 HTTP request 生命周期内直接运行。
- 服务重启时，遗留 Running Attempt 标记为 Error/Interrupted，不静默恢复。
- 首版不提供取消；若后续增加取消，取消必须形成明确 Error 或专用非 Gate 运行状态，不能产生
  Passed/Blocked。

GitHub 模式继续使用 PostgreSQL-backed queue，且只有权威 Attempt 可发布 standing decision。

## 19. 安全设计

### 19.1 本地 HTTP 边界

- 默认仅绑定 `127.0.0.1`。
- 验证 Host 和 Origin。
- Mutation API 要求同源和 CSRF token。
- 默认禁止跨域请求。
- 不接受浏览器直接传入未经登记的任意绝对路径启动检视。

### 19.2 Repository 边界

- Repository 添加时解析真实 root。
- 防止符号链接切换导致授权路径漂移。
- 每次运行重新校验 Repository identity。
- Review/Compute/Provider 配置不得位于被检视 Worktree。
- UI 不提供执行测试、构建、hook 或 Repository binary 的能力。

### 19.3 凭据

- 浏览器只提交和显示环境变量名。
- API 响应不返回 Secret。
- 日志、Event、SSE、错误响应和 Session Journal 统一脱敏。
- local-cli command 作为 argv 执行，不经 shell。
- local-cli 页面不得声称推理、网络或保留一定发生在本机。

### 19.4 UI 注入边界

Repository 文本、模型输出、Finding、Evidence 和错误 detail 均视为不可信数据：

- 默认以文本渲染。
- 不允许执行 HTML。
- 不允许 Repository 内容控制导航、链接或按钮。
- 外部链接显示目的地主机并使用安全打开策略。
- Code block 不通过 ANSI 或控制字符改变页面结构。

## 20. GitHub 演进设计

### 20.1 为什么与当前 Web UI 不冲突

Web 和 GitHub 共享：

- ReviewApplicationService。
- ReviewEvent。
- ReviewReport。
- Finding/Evidence/Gate 组件。
- Review Detail 页面。
- Usage、Coverage 和 Identity 展示。

平台差异只存在于 Review Source、触发、权威状态和发布 Adapter。

### 20.2 GitHub 来源模型

GitHub Run 附加：

- Installation ID。
- Repository full name。
- Pull request number。
- Base ref/head OID。
- Proposed head OID。
- Delivery ID。
- Check run ID。
- Authoritative Attempt ID。
- Standing decision 状态。
- Superseded 状态。

这些字段不进入 Review Identity，除非 PRD 已定义它们属于 Review Request Key 或 Merge
Candidate Identity。

GitHub Adapter 根据 Installation ID 获取短期 installation access token，并在服务端受控目录中
准备 Repository mirror 和隔离 review worktree。静态 PAT 只允许作为明确标记的 Pre-Alpha
单仓库烟雾测试配置，不是正式 GitHub App 执行路径；日志、事件和 API 均不得回显 token。

从 webhook 元数据得到的 Repository full name 是来源身份，真正传给 Pipeline 的
`repository_path` 必须来自安装级 mirror 管理器。每次执行都重新校验 base/proposed OID 与
Request Key；PR 分支或 Repository 文件不能影响可信 Review/Compute Policy、Provider Profile
或执行路径。

### 20.3 Web UI 完成后的最基本 GitHub 对接

首个 GitHub 里程碑只实现：

1. 同一公开 Repository 内、ready-for-review 的 PR。
2. `opened`、`reopened`、`synchronize`、`ready_for_review` 触发；`converted_to_draft`、base retarget、
   target branch push 和可信 Policy 变化使不再适用的 standing decision 失效。
3. 创建 queued Check。
4. Worker claim 后更新 in-progress。
5. 调用共享 Pipeline。
6. CAS 校验权威 Attempt 后发布 Passed、Blocked 或 Error。
7. Check Summary 展示 Gate、Finding 数、Coverage、Usage 摘要。
8. 有效 Evidence Span 映射为有限数量的 inline annotation。
9. Check `details_url` 指向 Web Review Detail。
10. 支持现有授权 Retry，Retry 创建新权威 Attempt。

Worker 领取任务前，Webhook 路径已经在 PostgreSQL 中持久化权威 Attempt、queued Check ID 和
不可变 `AttemptExecutionSnapshot`。Snapshot 包含 resolved refs、Review/Compute Policy 版本与
内容身份、Provider Profile 引用和可信执行参数，不包含 credential 值。Worker 使用该 Attempt ID
和 Snapshot 调用共享应用服务，不能在 claim 后重新读取可能漂移的当前 Policy。

PostgreSQL 同时保存 ReviewEvent、ReviewResult、publication state 和 publication intent/outbox。
Worker 更新已存在的 Check 为 in-progress/terminal；远程发布可以从 outbox 重试，但终态发布前
必须再次执行 CAS 校验。旧 Attempt 即使晚到完成，也只能保存审计结果，不能覆盖当前 standing
decision 或创建新的 standing Check。

暂缓：外部 fork、完整 bypass UI、多平台、跨候选 Finding 生命周期和自动修复。

### 20.4 GitHub UI 展示差异

Review Detail 顶部增加：

- `GitHub PR #N` Source Badge。
- Authoritative、Superseded 或 Audit-only Badge。
- GitHub Check 链接。
- 只有部署认证能把当前 Web 用户可靠映射到 GitHub actor，且 Attempt 仍权威时才显示 Web Retry。
- 基础 P2 集成优先使用 GitHub Checks requested action 完成授权 Retry；本机单用户 Web 只显示
  引导或禁用原因，不能冒充 GitHub actor。

本地 Web 页面不显示 Standing Decision，也不显示 Bypass 操作。

## 21. 响应式与可访问性

### 21.1 目标视口

- 现场演示优先：1366×768、1920×1080。
- 常规桌面：≥ 1024px。
- 平板：768–1023px，Sidebar 收起。
- 手机：首版保证查看结果可用；复杂配置以单列展示，不要求成为主要运行入口。

### 21.2 可访问性要求

- 明暗主题正文和常用控件达到 WCAG AA 对比度。
- 颜色不是唯一状态信号。
- 所有交互支持键盘。
- 焦点状态清晰可见。
- 实时状态使用节制的 `aria-live`，不在每次 heartbeat 打断读屏。
- 动效尊重 `prefers-reduced-motion`。
- 表格在窄屏转换为带字段标签的列表，而不是只做不可读横向压缩。

## 22. 加载、空状态和失败状态

### 22.1 Overview 空状态

首次启动显示：

- 添加 Repository。
- 创建 Provider Profile 并登记可信 Review/Compute Policy。
- 发起第一次检视。
- 打开无需 Provider 的 Demo Case。

不显示虚假的零趋势图。

### 22.2 活跃运行断线

浏览器断线时保留最后 sequence，重连后回放缺失事件。若服务重启并将 Attempt 标记为
Interrupted，页面展示 Error 和明确原因。

### 22.3 Session Insight 不可用

显示非阻断黄色告警和重新检测操作。Review 继续运行，Gate 不受影响。

### 22.4 统计未知值

Token、Cost 或 Retention 未知时显示 `Unknown` 与原因，不显示 0 或空白。

### 22.5 完整状态矩阵

| 状态 | 必需展示 | 允许操作 |
| --- | --- | --- |
| Loading/Skeleton | 保持稳定布局，不伪造业务数据 | 等待或离开页面 |
| Empty | 缺少 Repository、Profile 或 Review 的明确下一步 | 添加、配置或打开 Demo |
| Network reconnect | 最后已知 sequence、重连进度 | 自动/手动重连 SSE，不创建 Attempt |
| Awaiting Review | 排队原因、权威状态 | GitHub 授权场景可查看来源 |
| In Progress | 当前 Stage/Dimension、elapsed、最后事件时间 | 查看实时详情 |
| Passed | 无 blocking Finding、Coverage/Dimension 完整性 | 查看、导出、Retry |
| Blocked | Blocking Finding 和证据 | 修复后 Retry；GitHub 可逐 Finding Bypass |
| Coverage Error | 缺失/无法检视的具体 path 与原因 | 修复条件后 Retry |
| Merge conflict Error | Merge Tree 未构造、Identity unavailable | 修复冲突后 Retry |
| Provider failure | Provider、失败类别、已完成阶段 | 修复配置或网络后 Retry |
| Budget exhausted | Budget limit、估算/实际用量和失败点 | 调整可信 Compute Policy 后 Retry |
| Superseded | 原 Gate 与被取代说明 | 只读审计，不能 Publish/Bypass |
| Passed with Bypass | 原 Finding、接受原因、授权者和风险 | 查看审计；不表现成完全安全 |

所有重要交互必须定义 Hover、Focus、Active、Disabled、Loading、Success 和 Error 状态。Tooltip
必须可通过键盘访问；长 Hash、路径、Model 和错误文本不得破坏布局。

## 23. 演示方案

### 23.1 P0 离线原型主路径

1. 使用绑定 loopback 的本地 Preview 打开 Overview，展示 action-first 信息和明暗主题。
2. 打开真实 Pipeline 生成并校验的 Blocked Snapshot，展示 Finding、Evidence、Coverage 与 Gate。
3. 切换 Passed 与 Error Snapshot，说明三类确定性终态。
4. 打开带 `Mock data · Pre-Alpha` 标识的 GitHub 产品原型，展示未来的 Attempt 权威交互。
5. 全程不依赖 Provider、GitHub、Session Insight 或外部网络。

#### P1/P2 扩展示范

1. 从 New Review 选择提前准备的轻量 Repository，展示 Provider disclosure 并启动真实检视。
2. 在 Review Detail 观察 Pipeline/Dimension 实时进度。
3. 跳转 Session Insight 查看同一 Attempt 的回放。
4. 在测试 GitHub Repository 中展示 PR → Check → Web Detail；如外部服务波动，回到 P0 Snapshot。

### 23.2 必备截图

- Passed：绿色 Gate、零 blocking Finding、完整 Coverage。
- Blocked：红橙色 Gate、至少一个已验证 Finding 和代码证据。
- Error：深红色 Gate、失败 Stage、Review Identity 是否存在的明确说明。
- 每类至少保存一个主主题截图；明暗主题均通过视觉检查。

### 23.3 稳定性要求

- 预制 Case 无网络可打开。
- 快照通过当前 JSON Schema。
- 演示 Repository 内容和 Policy 固定。
- 真实运行失败不影响快照回放。
- Session Insight 未运行不影响 Web 结果展示。

## 24. 测试策略

### 24.1 单元测试

- ReviewEvent 验证、序号和脱敏。
- Gate 颜色和标签映射。
- Overview 指标分母。
- Provider Profile Secret 不回显。
- Review Source discriminated union。
- Session Journal 原子写入和追加行为。

### 24.2 集成测试

- `POST /reviews` 到终态 Result。
- SSE 初次回放、实时事件、断线续传和慢客户端。
- 服务重启把 Running Attempt 标记为 Interrupted。
- SQLite Result 与 JSON Schema 一致。
- Repository 和配置路径信任边界。
- GitHub Authoritative/Superseded 页面投影。

### 24.3 UI 测试

- 明亮、深色、跟随系统。
- Passed、Blocked、Error、Running、Awaiting、Bypass 和 Warning。
- 1366×768 首屏。
- Finding 多 Evidence Span。
- 超长 Repository/path/model/error text。
- 键盘导航和焦点。
- SSE 断线重连。
- 中英文技术文本混排。

### 24.4 端到端测试

- 当前 Worktree 成功检视。
- 带 blocking Finding 的真实检视。
- Merge 构造失败。
- Provider 失败。
- Session Insight 在线/离线。
- GitHub PR webhook → worker → Check → Web Detail。

## 25. 验收标准

### 25.1 本地 Web MVP

- 用户能登记本地 Repository、Provider Profile 和可信 Review/Compute Policy。
- 用户能选择三种本地检视来源并创建 Attempt。
- 页面在 1 秒内显示已持久化 Attempt 和初始状态。
- Pipeline 事件通过 SSE 可见。
- 终态页完整展示 Gate、Finding、Evidence、Coverage、Usage、Identity 和 Error。
- 刷新页面不丢失运行和结果。
- 明暗主题均可用，选择可保持。
- Secret 不出现在浏览器响应、日志、事件和 Session Journal。
- 三类 Demo Case 在断网状态可打开。

### 25.2 Session Insight

- 每个 Web Attempt 在 Session Insight 中只有一个稳定 Session。
- 运行中 Session 可实时更新。
- Pipeline、Dimension、Provider、Usage、Finding 和 Gate 可回放。
- 可用时关联真实 Agent Child Session；不可用时不猜测。
- Session Insight 故障不改变 Review Gate。

### 25.3 基础 GitHub

- 同仓库 ready PR 事件自动创建权威 Attempt。
- 新 Request Key 或 Retry 立即撤销旧 standing decision。
- Check 正确经历 queued、in-progress 和 terminal。
- 只有当前权威 Attempt 能发布 standing decision。
- Check 能跳转到统一 Web Review Detail。
- 旧 Attempt 完成后只保留审计结果，不能覆盖新 Check。

## 26. 实施顺序

### Phase 0 — 高保真离线原型与演示切线

- 冻结 `ReviewRunView`、路由、状态 Token 和三类 Fixture 契约。
- 建立 React/TypeScript/Tailwind 前端与 `mock` Data Source。
- 完成 action-first Overview，以及 Review Detail 的 Overview、Findings、Coverage、Identity 核心
  内容；其余 Tab 在 P0 先完成高保真只读形态，复杂 Retry/Bypass 动画进入 P0.5。
- 接入由真实 Pipeline 生成的 Passed、Blocked、Error 不可变快照并完成截图基线。

### Phase A — 应用层与事件契约

- 建立 ReviewApplicationService。
- 定义 ReviewEvent v1 和 Event Sink。
- 支持调用方预分配 Attempt ID，并分离执行、Gate、权威、发布与 Bypass 状态。
- 分离 Repository 来源身份与受信任的本地执行路径。
- 让 CLI 保持现有行为并接入统一服务。
- 固定安全字段和脱敏规则。

### Phase B — 本地 Web 后端

- Review、Repository、Provider Profile、Policy 和 Overview API。
- SQLite ReviewRunStore。
- 后台 worker 与中断恢复语义。
- SSE 回放与实时订阅。

### Phase C — Web UI

- 全局框架与明暗主题。
- Overview。
- New Review。
- Review Detail。
- Reviews、Repositories、Providers、Policies 和 Demo Cases。

### Phase D — Session Insight

- Worktree Review Session Journal。
- Session Insight `worktree-review` Reader。
- 实时追尾、Session 深链接和可验证 Child Session 关联。

### Phase E — 演示固化

- 三个真实 Demo Case。
- 截图基线。
- 无网络回放验证。
- 目标分辨率、主题和错误路径检查。

### Phase F — 最基本 GitHub 对接

- Webhook 到 Worker。
- Worker 到共享 Pipeline。
- Check 创建、更新和最终发布。
- Web Detail 链接。
- Authoritative/Superseded 展示和 Retry。

## 27. 实现前需要最终确认的开放项

以下事项不阻塞本文落盘，但在实现对应 Phase 前必须确认：

1. 本地 SQLite 和 Session Journal 的跨平台默认目录与迁移策略。
2. Session Insight 是否接受新增原生 Reader，及其稳定深链接/API 契约。
3. Evidence quoted text 是否允许以 opt-in 方式进入 Session Journal。
4. 首版是否导入已有 CLI JSON 结果，或只展示 Web 创建的 Attempt 和 Demo Case。
5. GitHub `details_url` 的部署地址、认证和访问控制方式。

前端栈已经确定为 React、TypeScript、Tailwind CSS、Framer Motion、Lucide Icons 和必要场景下
的 Recharts；Overview 默认展示最近 30 天，并允许切换时间范围。在以上开放项确定前，可以先
完成 ReviewEvent、应用服务、页面信息架构和三类 Demo Result，因为它们不依赖 GitHub 部署
地址或 Session Insight 最终深链接格式。
