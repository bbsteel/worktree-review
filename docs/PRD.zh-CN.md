# Worktree Review 产品需求文档

- 状态：第一阶段产品契约已可进入技术设计
- 日期：2026-08-27
- 可见性：公开产品文档
- 产品形态：基于完整工作树的代码检视，第一阶段提供高优先级 GitHub 合并门禁与本地 CLI
- 规范来源：`docs/PRD.md`；本文是同步维护的中文翻译，歧义时以英文为准

本文描述产品方向，不构成交付承诺。第一阶段要求是初始产品的规范；
后续能力在正式纳入第一阶段之前仅代表方向。

## 术语与概念模型

以下术语用于区分审查对象、审查所用信息、一次具体执行，以及当前有权影响
平台门禁的决定：

| 术语 | 定义 |
| --- | --- |
| 工作树检视（Worktree Review） | 在完整、隔离物化的结果仓库树中评估拟议变更的方法。diff 用于定位变化，完整代码树提供理解和验证所需的上下文；该方法不要求必须由 `git worktree add` 创建目录。 |
| 检视工作树（Review Worktree） | 为一个成功构造的合并候选物化出的不可变文件系统视图。它是产品层的检视环境，不一定是 Git linked worktree。 |
| 审查请求键（Review Request Key） | merge 构造前即可确定的键：源仓库、目标 ref、解析后的目标 head commit、提议 head commit、Review Policy 版本。即使 merge 构造失败，也能标识系统被要求构造和审查的对象。 |
| 合并候选身份（Merge Candidate Identity） | 源仓库、目标 ref、目标 head commit、提议 head commit及结果 merge-tree 标识。仅在 merge 构造成功后存在。 |
| 审查身份（Review Identity） | 合并候选身份加所应用的 Review Policy 版本，精确限定一个完整审查结论适用的对象。 |
| 审查上下文（Review Context） | 某次 Attempt 收集的代码、diff、测试、文档、变更请求元数据、外部结果及其他证据。它影响审查，但不构成审查身份。 |
| 审查执行（Review Attempt） | 从一个审查请求键启动的一次执行。它拥有 Attempt ID，并记录调用界面、Compute Policy 版本、模型来源、上下文快照、阶段结果、用量和成本。merge 成功后还绑定 Review Identity。 |
| 权威执行（Authoritative Attempt） | 平台集成指定的、当前有资格为该变更请求发布 standing decision 的最新 Attempt。即使 Review Identity 相同，更旧 Attempt 也已被取代。 |
| 当前有效决定（Standing Decision） | 当前真正生效的平台门禁结果。它只能来自权威 Attempt，始终绑定当前 Review Request Key；构造成功后还绑定 Review Identity，因此构造 `Error` 无需伪造候选身份。 |
| 审查结果（Review Result） | 某次 Attempt 的不可变输出。CLI 结果是一次性的，永远不会自动成为远程 standing decision。 |

简言之：Review Identity 表示“结论适用于什么”；Review Context 表示“执行参考了
什么”；Review Attempt 表示“哪次执行产生了结果”；Standing Decision 表示“当前
哪次结果拥有门禁权威”。

## 1. 产品概述

Worktree Review 是平台无关、策略驱动的 AI 代码变更检视产品。它不把 diff 当作完整
检视对象，而是在隔离的 Review Worktree 中检视真正会合入目标的结果树，发布有证据
支持的 finding，并依据用户拥有的 Review Policy 与 Compute Policy 判断合并候选能否通过。

GitHub 是首个平台集成，但不是产品边界。本地 CLI 使用同一语义，不要求先创建 PR。
第一阶段实现一个更小且失败关闭的子集。

可靠的合并门禁是本产品的原始动力，也是第一阶段最高优先级的交付结果。Worktree
Review 是产品和检视方法；GitHub Gate 是它首个具有权威性的执行界面，而不是一个独立、
只做简单合规检查的产品。

## 2. 问题陈述

独立开发者与小型开源项目常遇到：自动审查资格受计划限制、配额后需要手动触发、
语言与严重度不合需求、无法控制模型与成本、通用提示无法复用资深审查经验、只看
diff 会遗漏调用者/测试/配置/业务要求，以及评论机器人不能给出可靠门禁结论。

Worktree Review 将 Review Policy、Compute Policy、merge-candidate 上下文、证据强度、
覆盖率和 gate decision 作为一等产品概念。

## 3. 产品愿景

每个符合条件的合并候选，都应按照策略拥有者控制的规则得到上下文完整的审查。
结果必须说明审查了什么、发现了什么、证据有多强、成本多少以及门禁是否开放。

> 检视完整工作树，而不只是一份 diff；用证据控制合并门禁。

## 4. 产品形态与平台范围

| 界面 | 第一阶段职责 | 结果权威 |
| --- | --- | --- |
| GitHub 集成 | 自动审查符合条件的 PR，发布 inline finding 与持久 check，并支持可审计的 finding bypass。 | 绑定当前 Review Identity 与权威 Attempt 的 standing decision。 |
| 本地 CLI | 按需审查明确选择的本地合并候选，输出人类可读及机器可读结果。 | 仅针对所打印身份的一次性结果和进程退出码，不修改远程门禁。 |
| 其他平台 | 后续把原生变更请求、check、评论和授权映射到同一语义。 | 必须保留相同身份、证据、覆盖及失败关闭规则。 |

平台可以采用不同触发方式、展示和授权，但不得重新定义 Review Policy、证据等级、
覆盖完整性、finding 含义或 gate 计算。

## 5. 目标用户

### 5.1 第一阶段用户

维护 Git 代码的资深个人开发者或小项目维护者；使用 coding agent，希望在发布前和
PR 上都获得审查；审查本人或可信协作者分支；希望复用审查经验，控制语言、严重度、
证据、阻断规则、模型和单次成本。

### 5.2 后续用户

外部 fork PR 的开源维护者、私有仓库用户、小型团队、需要可审计仓库策略的组织，
以及 GitHub 之外的平台用户。

## 6. 第一阶段范围与要求

入口包括：同一公开 GitHub 仓库内、已 ready-for-review 的 PR；以及在 clean worktree
中，把明确目标 ref 与已提交 proposed head 进行比较的本地 CLI。

GitHub 入口的权威失效、重试、发布和阻止合并能力，其交付优先级高于两个界面的便利性
功能。本地 CLI 仍属于第一阶段，因为它在本地执行并暴露同一套检视和确定性门禁语义。

每个不同 Review Identity 都接受完整 Standard Review；每次显式 retry 也执行完整
审查，不跨候选增量复用结论。

Worktree Review 必须：

1. 在符合条件的 GitHub PR 打开、重新打开、转为 ready 或更新时自动审查。
2. 允许 CLI 选择目标 ref 与已提交 proposed head，执行相同语义。
3. 审查“把 proposed head 合入已解析 target head”产生的结果，而不是只审查 head。
4. 每个 Attempt 和结果绑定 Review Request Key；merge 成功后再绑定 Merge Candidate
   Identity 与 Review Identity。构造失败必须明确 merge tree 不存在。
5. Review Request Key 变化时立即撤销旧 standing gate；同键 retry 也先撤销旧决定，
   直到新权威 Attempt 完成。
6. 在不执行 proposed-change 代码的前提下准备完整、隔离、只读的精确工作区。
7. 按 mandatory、optional、excluded、unreviewable 规则收集代码和业务上下文。
8. 完成 Review Policy 要求的每个维度；任何 required dimension 未完成即 `Error`。
9. 发布包含严重度、证据强度、影响、支持证据和来源的 finding。
10. 支持 `critical`、`major`、`minor`、`suggestion`。
11. 审查启动后产生 `Passed`、`Passed with bypass`、`Blocked` 或 `Error`；只有能持久
    授权和审计的界面可产生 `Passed with bypass`。
12. 允许授权 GitHub 用户在完整审查后，以理由 bypass 当前身份的 blocking finding。
13. 允许授权 GitHub 用户对未变化的 Review Request 显式 retry，包括 `Error` 后或
    希望应用新 Compute Policy 时；retry 创建新的权威 Attempt。
14. CLI 对 `Passed` 成功退出，对 `Blocked`、`Error` 和无效调用使用不同非零退出码。
15. 提供修复建议但不修改 proposed change。
16. 允许用户把审查经验编码、版本化并存放在被审查仓库之外。
17. 允许选择 provider、model 和单次预算。
18. merge 无法构造、预算耗尽或完整审查无法结束时明确失败。
19. 每个界面展示 Review Request Key、Attempt ID、可用时的候选及审查身份、策略
    版本、模型用量、成本、覆盖和失败信息。

## 7. 第一阶段边界

### 7.1 延后能力

外部 fork PR、托管私有仓库、dirty snapshot、其他平台、跨候选增量结论、跨候选
finding 生命周期、只根据讨论重评、Deep Review、多 provider 路由/配额 fallback/
定时调度，以及校准数值置信度均延后。

### 7.2 非目标

Worktree Review 不是通用 coding agent、IDE 补全工具、自动修复系统、所有 linter/SAST
的托管替代、项目管理平台、团队分析面板、reviewer 分配器、测试生成器、冲突解决器
或自动提交服务。第一阶段可以给补丁示例，但不应用、提交或推送。

## 8. 产品原则

### 8.1 要么是精确合并候选，要么不审查

审查对象是 proposed head 合入 resolved target head 的结果，不是历史 merge-base。
任何 resolved commit 变化都会形成新候选。构造失败或冲突必须为 `Error`；只看 head
的 worktree 没有门禁价值。

### 8.2 决定受身份与权威 Attempt 约束

Review Request Key 在构造前存在，可用于调度、错误报告和审计，但不得伪装成成功
构造的 Review Identity。Merge Candidate Identity 和 Review Identity 只有在得到
merge-tree OID 后存在。平台 change-request ID 只是来源信息。

每次执行都是 Review Attempt；surface、Compute Policy、模型、上下文快照、阶段、
用量和成本属于执行来源，不改变 Review Identity 的含义。

Standing Decision 只对权威 Attempt 和 Review Request Key 有效；构造成功后还必须匹配
Review Identity。target ref/head、proposed head、retarget 或 Review Policy 变化会立即
失效旧决定并创建新权威 Attempt。同键显式 retry 也会创建新权威 Attempt，并在完成前
撤销旧决定。

每个变更请求同一时刻最多一个权威 Attempt。所有更旧 queued/in-flight Attempt 均被
取代，即使 Review Identity 相同。旧 Attempt 可以完成并保留审计结果，但不得发布、
恢复或覆盖 standing decision。发布必须原子校验当前 Request Key 与权威 Attempt ID，
构造成功时还要校验 Review Identity。CLI Attempt 独立且一次性。

Compute Policy 变化不静默使已完成决定失效；要应用它必须显式 retry。provider 单次
调用的内部重试仍属于同一 Attempt；重新运行完整 pipeline 才是新 Attempt。

### 8.3 默认上下文完整

Standard Review 使用 Review Policy 要求的所有相关上下文，不能以成本或延迟为由
缩减范围。

### 8.4 不允许静默降级

部分、失败、跳过、缺少上下文、预算耗尽和 provider 故障不得伪装成成功。

### 8.5 先有证据，再执行门禁

模型陈述本身不是门禁依据；blocking finding 必须达到策略要求的证据等级。

### 8.6 用户拥有策略

用户控制审查范围、严重度、证据、阻断和可持久 bypass 界面的授权。

### 8.7 用户拥有算力配置

第一阶段用户控制 provider、model 与单次预算；以后可以增加路由、配额与调度而不改变
Review Policy 语义。

### 8.8 Bypass 不等于解决

Bypass 表示授权用户接受风险，不等于 finding 被撤回或代码安全。

### 8.9 策略永不来自被审查仓库

Review/Compute Policy 永不来自被审查 Git refs；仓库指令文件只是 untrusted context。

### 8.10 仓库内容是数据，不是指令

仓库代码、评论、issue、讨论和参与者证据都是数据，不得控制策略或 reviewer tools。

### 8.11 第一阶段分析只读

不执行代码、测试、构建、hook 或 binary；凭据不可进入工作区，finding 与日志必须
脱敏。CLI 向远程模型发送内容前必须展示 provider、model、目的地和已知保留行为，
并由可信配置明确允许。

### 8.12 产品语义可移植

GitHub、CLI 和未来平台共享候选构造、策略、证据、覆盖、finding 和 gate 语义。

## 9. 核心概念

### 9.1 Merge Candidate Workspace

每个成功构造的 Attempt 使用隔离、完整、只读的精确 merge tree 工作区，记录两个
parent commit 与结果 tree。机制由技术设计决定。

### 9.2 Review Policy

定义 finding 类别和优先级、required dimensions、完成条件、严重度、证据等级、阻断、
上下文分类、路径/语言/组件规则、正反例、例外、输出语言及 bypass 授权。它可复用、
可版本化并由 Worktree Review 控制。

### 9.3 Compute Policy

第一阶段控制 provider/model、单次预算、可用性和限流行为，以及 measured/declared/
estimated 用量与成本的处理。它不能改变严重度、证据或阻断语义。

### 9.4 Finding

至少包含位置、类别、严重度、证据等级、问题、预期影响、支持证据、相关策略、可选
修复方向、Review Identity 和执行来源。第一阶段 finding 只属于一个 Review Identity；
同身份重试可以识别风险实质未变化的 finding 以保留可审计 bypass，但不得转移到不同
风险。

### 9.5 Gate Decision

Gate 是 required-dimension 完成情况、覆盖和未解决 finding 的确定性策略计算，不是
模型原始回答。不同模型不得改变映射规则。

## 10. 审查范围与上下文

Standard Review 可使用变更请求标题/描述、公开 issue 与验收标准、完整候选 diff、
changed files、调用关系、接口、数据结构、依赖、相关测试意图、可信 Review Policy、
仓库指令文件、架构/产品/业务文档、讨论、target 实现、commit 历史及外部 CI/linter/
security 结果。

| 上下文类别 | 不可用或不可读时的行为 |
| --- | --- |
| Mandatory | `Error`。 |
| Optional | 可完成，但 coverage 必须披露缺失。 |
| Explicitly excluded | 不在策略范围内，并披露 excluded。 |
| Unreviewable changed content | 必须被策略明确 exclude，否则 `Error`。 |

binary、缺失 LFS object 或超限文件可能 unreviewable，不得静默跳过。上下文完整是指
覆盖策略要求的范围，而不是拥有全部可能知识。

## 11. Review Mode

### 11.1 Standard Review

Standard Review 是第一阶段唯一模式。每个新 Review Request Key、授权 retry 和 CLI
调用都执行；覆盖所有未明确 excluded 的 changed content；完成并报告所有 required
dimension；每个候选完整审查一次。

任一 required dimension 失败或未开始即 `Error`。不跨候选复用结论；只可安全复用
immutable artifact/retrieval cache。

GitHub identity 变化或显式 retry 时，新 Attempt 先成为权威并撤销旧 standing decision。
无法停止的旧 Attempt 只能保留审计结果，发布时必须无法通过原子权威检查。CLI 固定
解析一次 refs，拒绝 dirty worktree。Draft PR 无 passing decision；外部 fork 第一阶段
明确 unsupported。

## 12. 严重度模型

| 严重度 | 含义 | 默认门禁行为 |
| --- | --- | --- |
| `critical` | 可利用入侵、授权绕过、凭据暴露、确定数据丢失或严重生产故障路径。 | 证据充分时阻断。 |
| `major` | 真实功能缺陷、重大回归、重要兼容破坏、并发/事务错误或显著性能问题。 | 证据充分时阻断。 |
| `minor` | 影响有限的边界或具体维护性/正确性/性能问题。 | 不阻断。 |
| `suggestion` | 可选改进、设计替代、命名、风格或非必要重构。 | 不阻断。 |

默认 `critical` 和 `major` 在至少 `supported` 证据时阻断；Review Policy 可修改。

## 13. 证据强度与置信度

| 证据等级 | 含义 | 是否可阻断 |
| --- | --- | --- |
| `insufficient` | 只有假设，没有足够支持。 | 永不阻断。 |
| `supported` | 上下文证明具体契约违反、可达失败路径或同等仓库依据。 | 可按策略阻断。 |
| `verified` | 可复现、逻辑必然或按策略独立确认。 | 可按策略阻断。 |

证据包括可达路径、违反契约、caller/callee 不匹配、必然失败、冲突测试/类型/配置/
仓库惯例或独立确认。模型自报确定度不是证据。数值置信度只能作为带模型来源的诊断，
第一阶段不能作为 blocking threshold。

## 14. Gate 状态

| 状态 | 含义 |
| --- | --- |
| `Awaiting review` | 平台已有符合条件的请求，但无 standing decision 且尚无 active review。 |
| `In progress` | 当前 Review Request 的完整审查正在执行。 |
| `Passed` | required dimensions 和 coverage 全部完成，且无未解决 blocking finding。 |
| `Passed with bypass` | 完整审查已完成，所有剩余 blocking finding 都有适用且授权的 bypass。 |
| `Blocked` | 完整审查已完成，仍有未 bypass 的 blocking finding。 |
| `Error` | required dimension、coverage 或有效 gate decision 无法完成。 |

`Error` 失败关闭，不能通过 finding bypass 变成 `Passed with bypass`。只能修正条件并
成功重跑；平台原生管理员绕过不改变 Worktree Review 的 `Error`。

Review Request 变化或同键显式 retry 时，旧状态在新权威 Attempt 启动前停止作为
standing gate。新身份不继承旧 pass 或 bypass；同身份 retry 可以按 §16 保留仍适用
的 finding bypass，但不继承旧 standing decision。CLI 不继承先前 gate/bypass。

## 15. Finding 处置与反馈

支持反馈的界面可标记：`confirmed`、`false positive`、`uncertain`、`accepted risk`。
这些是参与者意见，不是系统真相，也不会自行改变 gate；`accepted risk` 只有通过独立
授权 bypass 动作并给出理由后才构成 bypass。第一阶段讨论证据不自动撤回或降级
finding；代码变化产生新候选并完整重审。

## 16. Finding Bypass

第一阶段只有授权 GitHub 用户可在完整审查后 bypass blocking finding。未来平台必须
提供等价持久授权与审计。Bypass 必须：

- 要求明确理由；记录 actor、时间、仓库、change request、Review Identity、执行来源
  与 finding。
- 绑定当时的问题、严重度、影响和关键证据。
- 同 Review Identity 重审时，仅在风险实质不变时继续适用；实质、严重度、影响或
  关键证据变化时重新确认。
- 候选或 Review Policy 变化时过期；不影响无关或新 finding；始终与解决/撤回区分。
- 与 GitHub 原生管理员 bypass 共存。

授权默认参考 GitHub `write`、`maintain`、`admin`，策略可更严格。部分或失败审查的
finding 不可 bypass，因为 `Error` 代表未知风险。

## 17. 修复建议

可以提供修复方向、示例代码或 patch、建议测试、仓库相关示例，但不应用、提交或
推送。只有作者产生新候选并完成新审查后，修复才算验证。

## 18. 预算耗尽与不完整审查

预算无法覆盖完整审查时：gate 为 `Error`；报告预算耗尽；展示 completed、excluded、
optional-missing 和 unreviewed 范围；已发现 finding 可展示但不能 bypass；不能产生
pass。用户可修改 Compute Policy，并对同一 Review Request/Identity 创建新 Attempt。

provider failure、required dimension 不完整、mandatory context 不可用、in-scope 内容
unreviewable、workspace 缺失、merge conflict 等同样失败关闭。以后成功 Attempt 可
取代 `Error`；单纯修改 Compute Policy 不会自动改变状态。

## 19. 输出与本地化

用户可配置解释和交互语言；源码标识、API、代码和不宜翻译的精确错误保持原样。

所有界面展示：

- 与路径/行号关联的 finding、严重度、证据等级、可选模型置信诊断、证据、影响和
  适当修复建议。
- summary、gate state、Review Request Key、Attempt ID。
- merge 成功时的 Merge Candidate/Review Identity；失败时明确 tree 不可用及构造错误。
- 候选构造、workspace、context、每个 dimension 和 gate 阶段的完成/失败状态。
- mandatory、optional-missing、excluded、unreviewable、reviewed coverage。
- Review/Compute Policy 版本、模型、用量、估计/实际成本和失败信息。
- 分析数据目的地、provider、model 和已知 retention。

GitHub 还发布 inline finding、持久 check、finding bypass 和可观察的原生 override。
CLI 还输出 terminal report、稳定机器格式和退出码；包含 target ref/head、proposed head、
Attempt ID、Review Policy 和可用的 merge-tree OID；构造失败以 unavailable/null 表示。
CLI 不创建 bypass 或远程 check。

## 20. 模型与成本控制

第一阶段可配置 provider/model、单次最大预算、provider 不可用/限流行为，以及价格或
用量不确定时是否允许开始。必须区分 measured usage、用户声明限制、当前价格估计和
推断可用性，不得把猜测当权威或静默超预算。多 provider 路由、定时、配额优化和自动
fallback 延后。

## 21. Review 生命周期

### 21.1 共享 pipeline

1. 派生 Review Request Key、创建 Attempt ID、记录构造前来源；平台还原子指定该
   Attempt 是否权威。
2. 尝试把 proposed head 合入 target head。成功后完成 Merge Candidate/Review
   Identity；失败则输出绑定 Request Key 和 Attempt ID 的 `Error`，没有 tree/Review
   Identity。
3. 准备完整、隔离、只读 workspace。
4. 按 Review Policy 收集上下文。
5. 针对同一 workspace/context 执行所有 required dimensions。
6. 验证、去重和分类 finding。
7. 检查所有 required dimension；不完整时发布 partial finding/coverage 和 `Error`。
8. 执行确定性 gate 规则。
9. 通过调用界面发布/返回 finding、coverage、provenance、cost、summary 和 gate。平台
   只有在原子确认 Attempt ID 与 Request Key 仍权威，并在构造成功时确认 Review
   Identity 后，才能修改 standing decision。

### 21.2 GitHub 生命周期

1. PR 打开、重开、ready、更新、force-push、retarget、target/Review Policy 变化，
   或授权用户显式 retry 当前未变化请求（包括修正 Compute Policy/瞬时故障后）。
2. 解析当前 target 与 PR head。
3. 创建新 Attempt，并在调度/构造前原子设为权威，同时撤销旧 Attempt 的 standing
   decision，无论 Review Identity 是否变化。
4. 运行共享 pipeline 并发布持久 GitHub check。
5. 发布时原子检查当前 Attempt ID 与 Request Key，构造成功时还检查 Review Identity；
   被取代 Attempt 只保留审计。
6. 后续身份变化或 retry 返回步骤 2。

第一阶段必须提供授权 retry 动作。其呈现可以是 check action、命令或详情页；语义是
规范要求。Attempt 内 provider 请求重试不能代替完整审查 retry。

Draft PR 无 standing pass；外部 fork 与托管私有仓库第一阶段明确 unsupported。

### 21.3 本地 CLI 生命周期

1. 用户在本地 Git 仓库明确选择 target ref；proposed 默认为 committed `HEAD`。
2. CLI 检查 clean worktree，解析 refs，加载仓库外可信策略，并展示 provider/目的地/
   retention。
3. 创建独立 Attempt ID，对不可变 Git objects 运行共享 pipeline。
4. 写人类/机器结果，以 `Passed`、`Blocked`、`Error` 或 invalid invocation 对应退出。

结果只适用于打印的 Request Key、Attempt ID 和成功构造的身份；不建立远程 standing
gate，也不覆盖以后 commit 或未提交变化。

## 22. 反馈与产品验证

在拥有足够代表性样本前不设武断量化目标。第一阶段收集 finding disposition、gate 与
参与者判断是否一致、语言/严重度/证据/修复是否有用、参与者角色及无反馈情况。反馈
不是 ground truth；样本足够后维护独立裁决评测集。成本和延迟是运维诊断，不替代质量。

CLI 未显式 opt-in 时不得发送反馈、声明模型请求之外的源码或产品 telemetry。

## 23. 明确延后的技术决定

本 PRD 不决定：GitHub App/Action 具体机制、托管拓扑、平台 adapter interface、CLI
打包/语法/配置发现/机器 schema、候选构造与 workspace 机制、队列/数据库/cache、策略
schema、上下文检索、prompt/分析算法、可选置信校准、凭据代理和隔离、GitHub API/
webhook/check/comment 细节、未来平台 adapter、外部 fork sandbox、私有仓库披露、增量
审查、跨候选 finding、Deep Review、互动重评和多 provider 路由。

授权 retry 的具体 UI 也由 interaction design 决定，但“新建 Attempt、先撤销旧 standing
decision、发布时原子校验权威”的语义不得改变。

技术设计可以选择机制，但必须保留 Request/Identity/Attempt 的区分、精确候选、失败
关闭 `Error`、完整审查、权威 Attempt 发布规则和只读分析要求。
