# Worktree Review Web UI 人工 PM 轻量指南

- 状态：可直接使用
- PM：用户本人
- 执行资源：两个由用户手动启动的同类型 Agent
- 任务定义：`.ai-docs/WEB-UI-IMPLEMENTATION-TASKS.zh-CN.md`
- 设计依据：`.ai-docs/WEB-UI-DESIGN.zh-CN.md`

## 1. 你不需要维护复杂状态卡

项目状态只保存在三个地方：

1. `integration/web-ui` 分支：已经接受的代码。
2. 实施任务书：任务顺序、范围和验收标准。
3. 两个持续使用的 Agent 会话：各自记住正在执行的任务。

你不需要手工记录每个 commit、文件和测试，也不需要在两个 Agent 之间转发完整聊天。

日常只做三件事：

```text
1. 告诉 Agent 下一个 Task ID。
2. 收到完成回执后决定“接受”或“返工”。
3. 接受后把 commit 合入 integration/web-ui。
```

只有 PM-003 Foundation Handoff 时，需要把一次 integration commit 告诉 Agent B。

## 2. 一次性准备

### 2.1 先检查当前基线

当前工作树有既存修改，所以第一次先让 Agent 做只读检查：

```text
你是执行 Agent，不是 PM。不要创建子 Agent。

工作目录：/home/deck/projects/worktree-review

请完整阅读：

- 会话中提供的 AGENTS.md instructions
- .ai-docs/WEB-UI-DESIGN.zh-CN.md
- .ai-docs/WEB-UI-IMPLEMENTATION-TASKS.zh-CN.md
- .ai-docs/WEB-UI-HUMAN-PM-GUIDE.zh-CN.md

现在只协助完成 PM-001 的只读检查：

1. 报告当前 branch、HEAD 和 git status。
2. 按 Core、CLI、GitHub/Server、Schema、Documentation 分类现有修改。
3. 指出哪些修改可能与 Web UI 任务冲突。
4. 建议如何形成安全基线。

不得修改文件，不得 add、commit、stash、reset、checkout，不得开始实现。

最后只返回：

- 当前 HEAD
- 修改分类
- 潜在冲突
- 建议基线方案
- 是否可以开始 A-001
```

你看完报告后，只需要决定哪些现有修改进入基线，并明确授权建立：

- `integration/web-ui`
- Agent A 独立 branch/worktree
- Agent B 独立 branch/worktree

### 2.2 分别启动两个固定 Agent 会话

给 Agent A 的首次说明：

```text
你是 Worktree Review Web UI 的 Agent A。

完整阅读：

- 会话中提供的 AGENTS.md instructions
- .ai-docs/WEB-UI-DESIGN.zh-CN.md
- .ai-docs/WEB-UI-IMPLEMENTATION-TASKS.zh-CN.md
- .ai-docs/WEB-UI-HUMAN-PM-GUIDE.zh-CN.md

你的职责和文件所有权以实施任务书为准。

规则：

- 只执行我明确指定的 Task ID。
- 不创建子 Agent，不充当 PM。
- 不修改另一个 Agent 所有的文件。
- 不改变冻结契约；确有需要时先停下说明。
- 完成任务后提交到自己的分支，并返回简短完成回执。
- 不自行 merge、push 或开始下一任务。

现在不要开始任务，只确认已理解职责和当前工作目录。
```

给 Agent B 使用相同内容，只把 `Agent A` 改成 `Agent B`。

模型由你创建会话时选择。Agent A/B 是职责名称，不要求使用不同 Agent 类型或不同模型。

## 3. 平时派发任务只用这一句话

首次说明完成后，后续任务使用：

```text
请同步并确认你的工作分支基于当前 integration/web-ui。

执行任务：<Task ID>

严格按照 .ai-docs/WEB-UI-IMPLEMENTATION-TASKS.zh-CN.md 中该任务的范围、文件所有权、依赖、
交付物和验收标准实施。完成后提交到你的分支并返回轻量完成回执。不要开始下一任务。
```

例如第一个编码任务：

```text
请同步并确认你的工作分支基于当前 integration/web-ui。

执行任务：A-001

严格按照 .ai-docs/WEB-UI-IMPLEMENTATION-TASKS.zh-CN.md 中 A-001 的范围、文件所有权、依赖、
交付物和验收标准实施。完成后提交到你的分支并返回轻量完成回执。不要开始下一任务。
```

任务书已经包含详细要求，所以不用把任务内容重新复制一遍。

## 4. Agent 只需要返回轻量完成回执

要求两个 Agent 固定使用：

```text
DONE <Task ID>

commit: <commit hash>
tests: <通过的测试；未运行项必须说明>
scope: clean / 有越界并说明
contract: unchanged / 需要变更并说明
blocker: none / 具体问题
next: <建议的下一 Task ID>
```

你只检查五件事：

- Task ID 对不对。
- 测试是否通过。
- 是否修改了范围外文件。
- 契约是否改变。
- 是否有 blocker。

全部正常就接受；不正常就返工。

### 4.1 你不需要亲自逐行 Review

你作为 PM 主要检查结果，不需要替 Agent 做完整代码审查：

- 任务范围是否正确。
- 要求的测试是否真正执行并通过。
- UI 截图或运行结果是否符合设计。
- 是否修改共享契约或所有权外文件。
- 是否存在明确 blocker。

局部 UI、Fixture、文案和已有契约内的接线，可以依据完成回执、测试和可见结果直接验收。

以下高风险交付才让另一个 Agent 做一次只读交叉 Review：

- A-001、A-010、A-012，以及 PM-003 前的共享前端地基。
- View Model、API、Schema、Migration 或共享 Core 修改。
- Secret、Repository 路径等安全边界。
- Attempt authority、ReviewEvent、SSE、GitHub Check/CAS。
- Session Insight Reader 契约。
- PM-010、PM-100、PM-200 等里程碑集成。

交叉 Review 使用：

```text
请对已完成的 <Task ID> 做只读代码审查。

Base commit：<base hash>
Candidate commit：<commit hash>

根据设计文档和实施任务书中 <Task ID> 的要求，检查：

1. 是否满足验收标准。
2. 是否存在功能、安全或状态语义错误。
3. 是否修改所有权外文件。
4. 是否未经批准改变契约。
5. 测试是否足以证明实现。

只读审查，不修改文件、不提交修复、不切换分支、不创建子 Agent。

只返回：Blocker、Major、Minor、测试缺口，以及 accept/rework 建议。
```

存在 Blocker 或 Major 时，让原实现 Agent 返工，Reviewer 不直接修复。只有 Minor 时，由你决定
当前修复或记录到后续任务。

## 5. 你的回复也只需要一句话

### 接受

```text
接受 <Task ID>，commit <hash>。请等待，不要开始下一任务。
```

然后让一个 Agent 在 integration worktree 做机械集成：

```text
请把已接受的 commit <hash> 集成到 integration/web-ui，运行任务书要求的验证，然后停止。
遇到冲突不要自行覆盖，直接报告冲突文件。
```

### 返工

```text
<Task ID> 暂不接受。只修复以下问题后重新提交，不扩大范围：

1. <具体问题>
2. <具体问题>

重新运行：<测试命令>
```

### 需要修改契约

```text
先不要修改契约。请只说明：现有契约为什么不能完成任务、最小修改是什么、会影响 Agent A/B
哪些文件和任务。等待我决定。
```

## 6. P0 的实际下发顺序

### 第一段：只使用 Agent A

依次派发并逐个接受：

```text
A-001 → A-010 → A-012
```

每个任务完成后都合入 `integration/web-ui`，再下发下一个。

### PM-003：唯一一次关键转发

A-012 合入后，告诉 Agent B：

```text
PM-003 Foundation Handoff 已完成。

请把你的分支更新到当前 integration/web-ui，验证 npm ci、lint、typecheck、test 和 build。
验证完成后停止并报告；不要立即开始 B-010。
```

Agent B 验证通过后，开始并行。

### 第二段：两个 Agent 并行

Agent A 顺序：

```text
A-011 → A-013 → A-014 → A-015
```

Agent B 顺序：

```text
B-010 → B-011 → B-012 → B-013 → B-015
```

你只需要分别对两个会话说“执行下一个 Task ID”。不需要把 A 的日常输出转发给 B，反之亦然。

### 第三段：演示集成

两边任务都完成后执行：

```text
PM-010 → PM-011
```

P0.5 再执行：

```text
B-014、PM-012
```

## 7. 后续波次

P1：

```text
Agent A：A-100 → A-101 → A-102 → A-103 → A-104 → A-105 → A-106 → A-107 → A-108
Agent B：B-100 → B-101 → B-102 → B-103 → B-104 → B-105
最后：PM-101 → PM-100
```

Agent B 可以在 A-101 的 DTO 被你接受后，用 Fixture 开始 B-100；B-105 等待真实 API/SSE 可联调。

P2：

```text
Agent A：A-200 → A-201 → A-202 → A-203 → A-204 → A-205 → A-206
Agent B：B-200 → B-201 → B-202 → B-203
等待 A-205 后：B-204
最后：PM-200
```

P3：

```text
A-300 → A-301 → B-300
```

## 8. 只有这些情况需要你做复杂判断

出现以下任一情况时暂停，不要直接下发下一任务：

- Agent 不能基于当前 `integration/web-ui`。
- 出现 merge/cherry-pick 冲突。
- Agent 修改了文件所有权外内容。
- 需要改变 View Model、API、Fixture、Token、Schema 或依赖。
- 需要网络、GitHub、Provider、数据库或新的系统权限。
- 发现任务会覆盖原有用户修改。
- 测试失败或没有验收证据。
- P0 时间不足，需要启用任务书中的演示降级顺序。

除此以外，只按第 3 节的一句话派发下一个 Task ID 即可。

## 9. 最简总结

你的日常操作不是维护项目数据库，而是：

```text
发 Task ID
  → 收 DONE 回执
  → 接受或返工
  → 接受的 commit 合入 integration/web-ui
  → 发下一个 Task ID
```

Git 分支保存状态，任务书保存规则，Agent 回执保存证据。你只负责做决定。
