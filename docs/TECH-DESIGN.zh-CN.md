# Worktree Review 技术设计 — v1

- 状态：第一阶段 PRD 的首版技术落地计划
- 日期：2026-08-27
- 配套文档：`docs/PRD.zh-CN.md`；规范原文为 `docs/PRD.md`
- 范围：架构、语言、第三方组件、Identity/Attempt 持久化、权威发布语义、第一阶段用户
  配置和可检查的提示词层级；服务器端详细 schema、必需层级之外的具体 prompt 文案及
  交互设计仍由后续设计完成
- 规范来源：`docs/TECH-DESIGN.md`；本文是同步维护的中文翻译，歧义时以英文为准

本文解决 PRD §23 延后的决定。所有选择必须保留：精确 merge candidate 或不审查、
身份约束决定、失败关闭 `Error`、完整审查或可见失败、只读分析、策略永不来自被审查
仓库。

## 本设计使用的概念模型

| 概念 | 技术职责 |
| --- | --- |
| Review Worktree | 成功合并候选的只读、已校验文件系统物化；提供完整代码树上下文，但不要求是 Git linked worktree。 |
| Review Request Key | merge 前可用；按仓库、target ref、resolved heads 和 Review Policy 版本为调度、构造失败与审计提供键。 |
| Merge Candidate Identity | 仅在 `git merge-tree` 返回合法结果 tree OID 后完成。 |
| Review Identity | Merge Candidate Identity 加 Review Policy 版本，限定结论适用对象。 |
| Review Context | 某个 Attempt 收集的不可变、内容寻址快照，不能替代 Review Identity。 |
| Review Attempt | 一次 pipeline 执行，拥有 Attempt ID、Compute Policy、模型/用量来源和结果。 |
| Authoritative Attempt | change request 当前保存的 Attempt ID；只有它能修改 standing decision。 |
| Standing Decision | 原子检查 Review Request Key，并在构造成功时检查 Review Identity 后，由权威 Attempt 产生的平台 gate row 和 check；构造 Error 无需伪造身份。 |

数据库绝不能根据完成时间推断权威；后完成的可能是更旧、已被取代的 Attempt。

## 1. 语言选择

### 决定：Python（core、CLI、GitHub service 单一语言）

一个仓库、一个含共享 `worktree_review.core` 的 Python package，两个入口。GitHub server
及其权威 gate 是第一阶段交付重点；CLI 复用同一 pipeline 和确定性 evaluator：

| 入口 | 职责 |
| --- | --- |
| `worktree-review` | 本地 CLI，通过 PyPI、`uv tool install` 或 pipx 分发。 |
| `worktree-review-server` | GitHub App webhook receiver 与 review worker，Docker image 分发。 |

理由：第一阶段主要工作是 prompt、context assembly 和 finding processing，维护者的
Python 迭代速度最重要；目标用户能接受 Python ≥3.12 与 uv/pipx；并发主要等待 LLM
I/O，`asyncio.TaskGroup` 足够；Pydantic boundary、JSON Schema、mypy strict 和
Hypothesis 保证核心 gate 的可审计类型安全；Anthropic/OpenAI Python SDK 完善；Git
操作统一调用系统 CLI。

### 备选方案

备选：Go 的单 binary 与静态类型更强，但降低主要维护者迭代速度；TypeScript 的 GitHub
API 体验好但 CLI 分发和 runtime schema 成本更高；Rust 安全和 binary 最佳，但 prompt
相关开发速度和 LLM SDK 成熟度不足。若隔离层需要 native helper，可重新考虑 Rust。

## 2. 架构选择

### 2.1 顶层结构

```text
Surfaces
  worktree-review (Typer CLI)
  worktree-review-server (FastAPI GitHub App)
        │
Adapters
  worktree_review.platform.github
  worktree_review.platform.cli
        │
Core
  identity / candidate / review_worktree / policy / config / context / dimension
  provider / findings / gate / report / pipeline
  prompts (product-owned, inspectable hierarchy)
        │
Infrastructure
  system git · PostgreSQL · pgqueuer · LLM APIs
  detect-secrets · structlog · OpenTelemetry
```

产品语义全部位于 `worktree_review.core`；adapter 只映射 webhook、Checks API、终端、JSON 和
退出码，不得重新解释语义。采用 `src/worktree_review/` 布局，server-only dependency 放在
`worktree-review[server]` extra。

### 2.2 架构决定

**D1 — 使用 GitHub App，而不是 GitHub Action。**

Standing decision 的即时失效、安装级仓库外策略、持久 bypass 审计、GitHub 角色授权和
target branch push 事件不适合 run-scoped、repo-config-loaded 的 Action。App 接收事件、
保存策略、发布持久 check 并通过权限 API 验证 bypass。第一阶段 self-hosted。

**D2 — 在 bare object store 中用 `git merge-tree --write-tree` 构造候选。**

构造不得 checkout 或执行 proposed code；冲突必须失败关闭。Git ≥2.38 的
`merge-tree --write-tree` 在 object database 中产生 tree。成功后记录两个 parent 与
tree OID；构造前 Attempt 只有 Review Request Key，冲突/缺 object 输出没有 tree 或
Review Identity 的 `Error`。

Review Worktree 必须从原始 tree entry/blob OID 物化到新目录，并与源 tree 校验后 chmod
只读。不得使用会应用候选控制的 `export-ignore`、`export-subst`、smudge、clean 或
external driver 的 `git archive`/checkout filter。产品 metadata 放在 extracted tree
之外；目录相对创建必须拒绝 traversal，写入绝不跟随仓库 symlink；symlink 只作为链接
数据物化。

产品术语 Review Worktree 有意借用开发者对完整、隔离 Git worktree 的认知，但实现不使用
`git worktree add`：后者要求 commit/HEAD 形态的 checkout，并会引入本契约不需要的仓库
metadata 和 checkout 行为。

Server 使用专用无特权用户，CLI 使用调用用户；环境移除平台、installation 和 provider
凭据。Git fidelity 必须逐 byte 匹配真实 Git，因此不采用 go-git。CLI 在 Git 过旧时以
invalid invocation 退出。对于默认的 proposed source，CLI 通过临时 index 捕获当前工作树，
创建不可达但不可变的 snapshot commit：跟踪文件使用当前文件系统字节，包含未被忽略的
未跟踪文件，排除被忽略文件，并在 hash 时禁用 clean/smudge filter。用户的 index 和工作树
不会被修改。clean worktree 直接复用当前 `HEAD` commit。显式 committed proposed ref 不得
与未提交工作树变化同时使用，以免静默遗漏变化。

**D3 — 一个共享九阶段 pipeline，并显式记录阶段结果。**

顺序为：建立 Request Key/Attempt → merge 并完成身份 → Review Worktree → context →
dimensions → verify/dedup → completeness → gate → publish。Review Worktree 准备的
机器标识是 `prepare-review-worktree`；这是 Pre-Alpha 对 `worktree-review.cli.result/v1`
的原位更新，原先 wire value 为 `prepare-workspace`。每阶段追加 `completed`、
`failed`、`not-started`；fatal failure 短路为 `Error`，partial finding 可展示但不可
bypass。

GitHub stage 1 在入队前事务性创建 Attempt 并设为权威；stage 9 使用 compare-and-set，
要求持久化的权威 Attempt ID 与 Request Key 匹配，构造成功时再要求 Review Identity
匹配。失败则只保存 superseded 审计结果，不修改 standing decision。

**D4 — 确定、纯函数 gate evaluator。**

输入为 dimension outcomes、coverage、findings、bypasses 和 Review Policy，输出
GateState。模型只影响 finding 是否存在，不参与状态映射。使用 table-driven 与 property
tests 保证“required dimension 不完整必为 Error”等性质。

**D5 — Worktree Review 控制的版本化、内容寻址 YAML Policy。**

Review/Compute Policy 分离；每份具有 semver 和 canonical parsed bytes 的 SHA-256。
CLI 的 `--policy` 可省略，省略时使用产品拥有的内置 Review Policy。普通 Provider 配置是
`~/.config/worktree-review/config.yaml`（或显式路径）中的最小 YAML，包含远程
provider/key/model（可选自定义 URL）或本地 CLI command。本地 command 必须选择产品提供的
adapter：`worktree-json`、`prompt-json` 或 `prompt-text-json`；默认是 Worktree Review
JSON stdin/stdout 协议。普通路径派生每次调用最多 4096 个输出 token，且不设置美元预算；
同时对完整本地 command 配置派生不含 secret 的 fingerprint，并携带可选的 command 数据
目的地与 retention disclosure。`--compute-policy` 仍是需要直接控制 Compute 的高级路径，
其外部 schema 只接受远程 Provider。所有自定义策略/配置路径都必须在 worktree 外。GitHub
按 installation 保存到 Postgres。文件配置均以版本化 JSON Schema 验证并失败关闭；`AGENTS.md`
等只作为 untrusted context，永远不是策略或配置。

**D6 — Provider 约束的结构化 finding，加 grounded evidence 校验。**

每个 dimension 要求 provider-native JSON Schema 输出。verify 阶段检查 evidence span
的路径、行范围和 quote 确实存在于声明的强类型 source 及匹配的不可变 snapshot；第一阶段
source 包括 `review-worktree`、`target-tree`、`merge-diff` 和 `metadata`，已知时同时携带
`change_kind`。`context_class` 只是展示标签，不是 provenance。因此 target-tree body 中的
quote 不能为声明来自 Review Worktree 的 span 建立证据，即使文本相同。未 grounded 的 claim
不得标为 `supported` 或 `verified`。grounding 最多派生 `supported`；`verified` 需要 provider
输出之外的独立可信验证 provenance，所以第一阶段会封顶 provider 自报的 `verified`。
所有 finding 先完成验证再分组；重复组采用最强证据和最高严重度的保守合并，输入/provider
顺序不能丢弃更强 finding。按 path、normalized span、category 和 problem hash 确定性重算
fingerprint；没有合法 span 时使用 sentinel path，绝不信任 provider fingerprint。

提示词资源是 `worktree_review.prompts` 下由产品拥有的 package data。每个 dimension 按
`00-product`、`10-safety`、`20-review`、`30-dimensions/<dimension>`、`40-output` 的顺序
组合；CLI 通过 `worktree-review prompts --dimension <id>` 暴露实际层级。提示词资源永远不从
被审查仓库加载，也不是策略覆盖机制。

**D7 — 有界 Provider 调用与高级预算控制。**

每份 Compute Policy 都携带每次 Provider 调用的硬性最大输出 token。普通 `--config` 路径
派生 `max_output_tokens_per_call: 4096`，记录输入 token 预估但不为其预测美元费用，真实
支出由 Provider 账户控制。首次调用前报告调用次数、预计输入 token 和单次输出上限；完成后
明确报告 measured usage 以及费用是否可得。Provider handoff disclosure 同时适用于远程 SDK
和本地 command。本地 command 不被假定为无网络；其 command/adapter/目的地/retention 的
fingerprint 会进入派生 Compute Policy identity 和结果。

高级 `--compute-policy` 提供每次检视预算（内部派生策略可不设置；外部高级 schema 必须设置）：

1. Pre-flight：按 provider tokenizer 估计 assembled context；超预算则拒绝，除非策略
   明确允许不确定价格/用量下开始。
2. In-flight：每次 provider response 后记录实际用量；剩余预算不足时停止调度后续
   dimensions。
3. Exhaustion：gate 为 `Error`，披露 completed/skipped/unreviewed；finding 可见但
   不可 bypass。

Usage 区分 measured、declared、estimated，并按 Attempt 持久化。普通配置不会把未知的
Provider 价格变成预测，也不会产生 Worktree Review 自己的美元预算。

**D8 — PostgreSQL 状态，pgqueuer 同库队列。**

身份变化事件或授权同身份 retry 会在同一事务中创建新 Attempt ID、写入 change
request 的 `authoritative_attempt_id`、撤销旧 standing decision，再入队。Job 以
Attempt ID 唯一，而不是 Review Identity，因为同身份必须能合法重跑。

Queued superseded job 丢弃；in-flight 可完成，但 stage 9 原子比较 Attempt ID 与当前
Request Key，构造成功时再比较 Review Identity，之后才能修改 `gate_decisions`/发布
check。旧同身份 Attempt 不能覆盖新结果。`tenacity` provider-call retry 留在同一
Attempt；完整 pipeline 重跑总是新 Attempt。第一阶段不引入 Redis/SQS/NATS/Celery。

发布是单次 `RUNNING → PUBLISHED` CAS。对仍是 standing 的 Attempt 重复发布相同结果时，
返回原结果且不新增 decision；不同结果返回 state conflict。数据库唯一约束保证每个
Attempt 最多有一个 gate decision。GitHub retry delivery 按 `(installation_id, delivery_id)`
幂等；delivery 记录与新 Attempt 在同一事务写入，重投直接返回第一次的 Attempt，不会再次
取代它。

CLI 除可选 immutable content cache 外无状态；cache 不得缩减范围或复用结论。

**D9 — Append-only audit 与已发布状态自审计。**

Bypass、gate transition、invalidation、policy、模型和成本均追加审计。Bypass 绑定
Review Identity、finding fingerprint 和风险快照，并按身份/策略失效及“实质未变化”
确定性匹配。

发布 check 包含 Attempt ID 短 fingerprint，details URL 指向数据库决定。Fingerprint
只用于描述，不是并发锁；权威来自 D8 的事务 CAS。服务通过 webhook 与定期 sweep
比对平台状态和 `gate_decisions`；不匹配记录 tamper event、重发正确状态并通知 owner。
评论 bypass 必须实时查 GitHub role，不能信任评论文本；可观察的 GitHub admin
override 记录审计。

**D10 — CLI 契约。**

- stdout 人类报告；`--format json` 输出 `worktree-review.cli.result/v1`。Pre-Alpha
  允许该 schema 原位更新标识符；Review Worktree 准备阶段为
  `prepare-review-worktree`，不再使用 `prepare-workspace`。
- Exit code：0 Passed、1 Blocked、2 Error、3 invalid invocation。invalid invocation 包括
  无法解析 ref、策略位于仓库内、Git 过旧、互斥的 source 选择参数，或无法表示的工作树
  snapshot；CLI 永不产生 `Passed with bypass`。
- 默认 CLI 检视相对于 `HEAD` 的当前工作树 snapshot；`--target` 选择其他 target ref，
  `--commits N` 检视从 `HEAD~N` 到当前工作树 snapshot 的内容，`--proposed` 在 clean
  worktree 上选择显式 committed proposed ref。机器结果会把默认 source 标记为
  `proposed_ref=WORKTREE`，报告 `proposed_source=current-worktree-snapshot`，并在
  `proposed_head_oid` 报告其不可变 snapshot commit。target 和 proposed source 在共享
  pipeline 启动前只捕获一次，之后的变化不属于该结果。
- `--policy` 可选，省略时使用内置 Review Policy。普通 `--config` 配置远程
  provider/key/model（可选自定义 URL）或本地 CLI command 和产品 adapter，并派生每次调用最多
  4096 个输出 token、且不设置美元预算；高级 `--compute-policy` 仍可直接控制 Compute，且
  只接受远程 Provider。任何 Provider handoff 前打印 provider/model/destination/retention；
  local command 还打印配置 fingerprint；feedback/telemetry 默认不发送。
- CLI 在 Provider 调用前打印 call plan，并把它与 usage 一起放入机器结果；普通配置在
  Provider 返回时报告 measured 输入/输出 token，否则提示到 Provider 账户查询费用。
- `worktree-review init` 交互式选择远程 Provider/key 或本地 command，检查本地 executable
  是否可用但不执行它，并写入 mode-600 的可信默认配置。直接运行 `worktree-review` 与显式
  `review` command 等价。
- text 和 JSON 模式都把非权威的准备、阶段和当前 dimension 进度写入 stderr，完成后包含
  耗时；JSON stdout 只保留版本化结果文档。
- `worktree-review prompts --dimension <id>` 输出该 dimension 使用的可信产品提示词层级。
- 每次调用生成 Attempt ID。构造失败输出 Request Key 和 `merge_tree_oid: null`；成功
  还输出 Merge Candidate/Review Identity。CLI Attempt 不进入 server 权威状态。

**D11 — 不可信内容和 secret hygiene。**

仓库内容始终作为 quoted/delimited data；tools 和权限只来自可信策略。Finding 与日志
发布前经过 detect-secrets 脱敏。

**D12 — 第一阶段部署。**

单 Docker image 运行 webhook HTTP 与 embedded pgqueuer worker，旁接 Postgres；CLI
通过 PyPI/uv/pipx。开发 webhook 用 smee.io/ngrok；无独立 worker fleet、scheduler 或
service mesh。

**D13 — GitHub inline publication 是经测试的映射层。**

Core finding 使用 merge tree 绝对行号；GitHub adapter 把 controlled diff hunk 映射到
可评论位置。GitHub 三点 PR diff 与 Worktree Review 的 target-head→merge-tree diff 不同，
target-side 行可能无法 inline。降级顺序必须披露：inline annotation/comment → file-level
comment → check summary（保留完整坐标和原因），不得静默丢 finding。Annotations 每次
API 最多 50 条，级别由严重度映射。

**D14 — GitHub retry 创建新权威 Attempt，不改变 Identity 定义。**

第一阶段 App 提供当前 Review Request 的授权 retry，首选 Checks requested action，
details-page action 可替代。处理时重新解析 refs 和 Review Policy，再执行 D8 事务。
输入变化自然形成新 Request/Identity；未变化则是 same-identity retry。新 Compute
Policy 记录在 Attempt，不加入 Review Identity。授权结果、原因、delivery ID、旧/新 Attempt ID
追加审计；GitHub 重投按 delivery key 幂等确认。

## 3. 第三方组件选择

| 关注点 | 选择 | 说明 |
| --- | --- | --- |
| 语言工具链 | Python ≥3.12 + `uv` | env、lock、build、publish。 |
| 构建/打包 | `hatchling` + `src/worktree_review/` | 单 package，server extra，两个 console entry。 |
| CLI | `typer` | 基于类型提示，退出码由本项目控制。 |
| HTTP server | `fastapi` + `uvicorn` | Webhook、details、health。 |
| HTTP client | async `httpx` | Provider 和 GitHub 统一异步纪律。 |
| YAML | `pyyaml` | Policy；hash 基于 canonical parsed form。 |
| Schema | Pydantic v2 + `jsonschema` | JSON Schema 为 policy/result 单一事实来源。 |
| Git | system Git ≥2.38 + asyncio subprocess | `merge-tree --write-tree`、raw tree/blob enumeration、ref resolution。 |
| GitHub | `githubkit` | typed webhook、HMAC-SHA256；PyGithub 可 fallback。 |
| Database | PostgreSQL 16 + `asyncpg` | Standing decision、bypass、identity；手写 SQL。 |
| Migration | `alembic` | 启动时应用 plain SQL migration。 |
| Queue | `pgqueuer` | 同 Postgres，job 以 Attempt ID 唯一。 |
| LLM SDK | 官方 `anthropic`、`openai` | Structured output 与 usage。 |
| Token | `tiktoken` + Anthropic count API | Provider-specific input estimate，response usage 权威。 |
| Secret redaction | `detect-secrets` | Findings/log；必要时考虑 gitleaks。 |
| Retry | `tenacity` | Compute Policy 下的 provider transient retry。 |
| Logging | `structlog` | JSON，每条记录含 Attempt ID。 |
| Tracing | OpenTelemetry Python | Stage span、provider latency/cost。 |
| Testing | pytest、pytest-asyncio、Hypothesis、testcontainers | Gate property test 与真实 Postgres integration。 |
| Quality | ruff + mypy strict + pre-commit + GitHub Actions | 每次 push 执行。 |
| Release | `uv build` → PyPI + Docker | 单 binary CLI 后续考虑。 |

第一阶段明确不选：go-git/pygit2、LiteLLM/多 provider router、Celery/Redis/SQS/NATS、
ORM、vector database 和默认 hosted telemetry backend。

## 4. Server 数据模型草图

- `installations`、`repositories`
- `change_requests`：当前 Request Key、构造成功时的 Review Identity、
  `authoritative_attempt_id`
- `review_policies`/`compute_policies` 与各自 `policy_versions`
- `review_request_keys`：repo、target ref/head、proposed head、Review Policy hash
- `merge_candidate_identities`：请求 Git 字段加 merge-tree OID
- `review_identities`：候选加 Review Policy version
- `review_attempts`：Attempt ID、Request Key、可选 Review Identity、authority/
  supersession、surface、stages、models、usage、cost
- `context_snapshots`、`dimension_runs`
- `findings`：fingerprint、severity、evidence band、grounded spans
- `gate_decisions`：Review Request Key、可选 Review Identity、source Attempt ID、
  state、standing、validity
- `bypasses`：actor、reason、risk snapshot、expiry
- `audit_events`：append-only

`authoritative_attempt_id` 是关键并发选择；完成时间永远不决定权威。完整 DDL 后续设计。

## 5. PRD 合规检查点

| PRD 不变量 | 技术落实 |
| --- | --- |
| 精确候选或不审查（§8.1） | D2；冲突/缺 object → Error。 |
| 身份约束、即时失效、同身份 Attempt 顺序（§8.2） | D8；事务替换权威 Attempt，发布 CAS 检查 Request、Attempt 与适用的 Identity。 |
| 上下文完整、无静默降级（§8.3/8.4） | D3 stage outcome 与 coverage。 |
| 证据先于 enforcement（§8.5/13） | D6 grounded span。 |
| 策略不来自仓库（§8.9） | D5 CLI path restriction/GitHub installation storage。 |
| 只读与凭据隔离（§8.11） | D2 Review Worktree/env，D11 redaction。 |
| 确定性 gate（§9.5） | D4 pure evaluator。 |
| 预算失败关闭（§18/20） | D7。 |
| 平台状态完整性与 override 可见（§16/19） | D9 fingerprint、reconcile、live auth。 |
| CLI one-shot 与退出码（§6/19/21.3） | D10。 |
| GitHub 未变化身份 retry（§6/21.2） | D14 + D8 新权威 Attempt 事务。 |

## 6. 风险与开放问题

1. `git merge-tree` 的 submodule、LFS、rename 等边界需 adversarial fixture spike。
2. In-flight supersede 依赖 publish-time Attempt+Identity CAS；integration test 必须模拟
   force-push 和 same-identity retry，尤其旧 Attempt 最后完成。
3. Grounded evidence 可能引用 diff 之外上下文；span schema 必须覆盖所有 context class。
4. Provider price table 会漂移；Compute Policy 必须版本化价格并披露 estimate/measured。
5. Bypass “实质未变化”匹配最细微，实施前需要独立设计。
6. Hosted/self-hosted 默认分发及 bypass UX 尚未最终决定；comment command 是第一阶段
   fallback。
7. Target advance 会使同分支所有 open PR 失效并可能形成 merge convoy。第一阶段通过
   queue coalescing、快速无 token merge 构造、预算上限和运维 merge window 缓解。

后续候选能力：

- Input-identical revalidation：重新执行身份、构造、Review Worktree、context，比较实际输入
  集合的 content hash；完全相同才恢复旧决定，否则完整重审。外部 discussion/issue/CI
  也必须快照并参与 hash。它需要 PRD 修订，第一阶段不启用。
- GitHub Merge Queue：处理 `merge_group`，以 merge-group candidate 为 Review Identity。
- 更远期可允许 Review Policy 显式 opt-in relatedness-aware re-review，默认仍失败关闭。

## 7. 实现适配清单

当前 skeleton 早于本次澄清，按以下顺序收敛，保证中间状态失败关闭：

1. 增加 `ReviewRequestKey` 与 Attempt ID；只在 merge 成功后创建
   `MergeCandidateIdentity`/`ReviewIdentity`；构造错误保留 Request Key，tree 为 null。
2. Pipeline stage 1 从“已完成 Review Identity”改为建立 Request Key/Attempt，stage 2
   完成成功身份，同时保留九个外部 stage。
3. Surface-neutral report 与 `worktree-review.cli.result/v1` 同步增加 Attempt ID、Request Key
   和可选成功身份；terminal/JSON renderer 同时更新。
4. 已在 `worktree_review.server.state` 实现 GitHub
   `change_requests.authoritative_attempt_id` 事务、Attempt-keyed job 和 stage-9 CAS；测试
   覆盖旧同身份 Attempt 最后完成。
5. 已在 `worktree_review.platform.github.retry` 与 `webhooks` 实现 D14 授权 retry；provider
   call retry 留在同一 Attempt，完整 rerun 创建新 Attempt。
6. 用 verified raw tree/blob materialization 替换 archive；metadata 放在 repo namespace
   外；测试 marker collision、absolute/relative symlink、`export-ignore`、`export-subst`、
   traversal 和 unusual Git paths。
7. Review Policy glob 必须精确处理 POSIX path 及 `.env`、`.github/**` 等 leading-dot
   path；证明 exclusion/mandatory 不会静默漏掉 dotfile。

英文文档是规范原文。`docs/PRD.zh-CN.md` 与本文是维护性翻译；任何规范语义变更都必须
在同一 commit 同步两种语言。
