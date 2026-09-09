# Worktree Review 使用说明

本说明介绍当前可用的 Worktree Review 使用界面：本地
`worktree-review` CLI。内容包括安装、最小 Provider 配置、内置 Review Policy 与提示词
层级、检视来源、输出格式和退出码。

GitHub server 目前已经有部分状态、webhook、retry 和 Checks adapter，但检视 worker
尚未接入共享 pipeline，因此本阶段还不是端到端的面向用户的 GitHub 检视服务。

## 要求

- Python 3.12 或更新版本。
- Git 2.38 或更新版本。Worktree Review 使用 `git merge-tree --write-tree`。
- 一个 target 和 proposed commit 都能解析的本地 Git 仓库。
- 远程 Provider 的 key 和 model（可选自定义 URL），或者一个配合内置 adapter 的本地检视命令，二选一。

CLI 不会执行 proposed change 中的代码。它会构造精确的 merge candidate，物化临时的
只读 Review Worktree，按策略收集上下文，再把生成的检视请求交给配置的 Provider 或本地 command。

## 安装

从本仓库开发时：

```bash
uv sync
uv run worktree-review --version
```

安装已发布的包时，使用环境中适合的包管理器：

```bash
uv tool install worktree-review
# 或
pipx install worktree-review
```

安装后的命令是 `worktree-review`。只有直接使用本仓库虚拟环境时才需要 `uv run` 前缀。

## 快速开始

交互式创建可信默认配置，然后在仓库中运行检视：

```bash
worktree-review init
worktree-review
```

`init` 会把远程 Provider/key 或本地 command 写入
`~/.config/worktree-review/config.yaml`。它只检查本地 executable 是否能找到，不执行该命令，
也不会发出远程凭据请求。`worktree-review review` 仍是显式等价写法。

## 配置文件

正常使用本地 CLI 时，面向用户的配置是一份小型 YAML 文件。它可以选择带 key 和 model
（可选自定义 URL）的远程 Provider，或者选择一个本地检视命令。Review Policy 是可选的：
省略 `--policy` 时，Worktree Review 使用内置的默认策略。推荐使用 `worktree-review init`
创建配置；如果由 secret store 或部署系统管理，也可以手工维护 YAML。

把 [config.example.yaml](config.example.yaml) 复制到可信的默认位置，再替换 key 引用：

```bash
mkdir -p ~/.config/worktree-review
cp config.example.yaml ~/.config/worktree-review/config.yaml
export ANTHROPIC_API_KEY='从 secret store 获取的密钥'
```

默认配置文件是：

```text
~/.config/worktree-review/config.yaml
```

设置了 `XDG_CONFIG_HOME` 时，用它的值替换 `~/.config`。例如，
`XDG_CONFIG_HOME=/etc/xdg` 时，默认路径是 `/etc/xdg/worktree-review/config.yaml`。

也可以用 `--config PATH` 选择其他可信配置文件：

```bash
worktree-review review --config /secure/worktree-review/config.yaml
```

解析符号链接后，配置路径仍必须位于被审查 worktree 之外。配置文件位于仓库内部时，
CLI 会拒绝调用并返回退出码 `3`。

### 最小远程配置

普通配置只需要 Provider、凭据和要使用的 model：

```yaml
provider: anthropic
key: ${ANTHROPIC_API_KEY}
model: claude-sonnet-4-5
```

`provider: openai` 的配置方式相同。省略 `url` 时使用标准 endpoint；如果使用已批准的
OpenAI-compatible 或其他自定义 endpoint，再填写 `url`。`model` 可以省略，此时使用该
Provider 的内置默认值。`key` 可以是可信文件中的明文 secret，但更推荐使用
`${ANTHROPIC_API_KEY}` 这样的环境变量引用。

### 本地 CLI Provider 与 adapter

也可以配置本地 executable：

```yaml
provider: local-cli
command:
  - /usr/local/bin/my-review-provider
```

数组中的每一项都是一个参数；命令行 flag 要分别写成后续数组项，不支持 shell pipeline、
替换或重定向。命令不会经过 shell 启动。默认使用 `worktree-json` adapter，并从 stdin 接收一个
JSON 对象：

```json
{
  "system": "...",
  "user": "...",
  "response_schema": {"...": "..."},
  "dimension_id": "correctness",
  "max_output_tokens": 4096
}
```

它必须向 stdout 写入一个 `dimension-findings.v1` JSON 对象（例如 `{"findings": []}`）并以
状态 `0` 退出。

如果已有命令能够从 stdin 接收 prompt，可以使用产品 adapter，不必另外开发项目专用 wrapper：

```yaml
provider: local-cli
command:
  - claude
  - --print
adapter: prompt-text-json
```

`prompt-json` 会把渲染后的 system/user prompt 写入 stdin，并要求 stdout 是一个 JSON 对象。
`prompt-text-json` 还会从 fenced 或轻度装饰的响应中提取一个 JSON 对象。这两个 adapter 都不会
把任意自然语言可靠转换为 finding；命令仍必须被指示或配置为返回 `dimension-findings.v1` 结构。
需要 response schema、dimension metadata 作为输入字段的自定义 wrapper 应使用 `worktree-json`。

如果 command 会把内容转交给 Provider 或服务，可以加上本地 command 的 disclosure metadata：

```yaml
data_destination: "Company review gateway"
known_retention: "Retained according to the gateway policy."
```

省略时，Worktree Review 会展示保守的 command-defined 默认值。本地 executable 不是它不会联网
或 retention 在本机的证明。CLI 会明确说检视内容将交给配置的 command，并展示不含 secret 的配置
fingerprint；传输 disclosure 不会打印 command 参数。本地工具可能不报告 token 用量，因此结果
中的用量和成本可能是未知的。

### 配置生成的 Compute Policy

`--compute-policy PATH` 仍然可供需要直接控制 model、单次输出上限、预算、token 价格、
retention 文本和传输同意的部署使用。它不能和 `--config` 同时使用。完整的高级 schema
和示例见 [examples/compute-policy.yaml](examples/compute-policy.yaml)。普通用户配置会生成
安全的运行默认值，建议从上面的最小配置开始。

### Review Policy

Review Policy 控制检视什么内容，以及哪些经过验证的 finding 会阻断 gate。文档 schema
是 `worktree-review.review-policy/v1`。

用户不需要提供 Review Policy。省略 `--policy` 时，CLI 使用可信的内置默认策略：
`correctness` 和 `security` 是 required dimensions，`critical` 和 `major` 在证据等级至少
为 `supported` 时阻断，`AGENTS.md` 和 `CLAUDE.md` 是 optional context。只有需要不同的
可信检视标准时，才使用 `--policy PATH`。

自定义策略示例：

```yaml
schema: worktree-review.review-policy/v1
version: 0.1.0
required_dimensions:
  - correctness
  - security
blocking_severities:
  - critical
  - major
minimum_blocking_evidence_band: supported
context:
  max_file_bytes: 1048576
  excluded_globs: []
  mandatory_globs: []
  optional_globs:
    - AGENTS.md
    - CLAUDE.md
```

字段：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `schema` | 是 | 必须是 `worktree-review.review-policy/v1`。 |
| `version` | 是 | 记录在 Request Key 和 Review Identity 中的语义化版本。 |
| `required_dimensions` | 是 | 一个或多个不重复的维度 ID。 |
| `blocking_severities` | 否 | 可以阻断 gate 的严重度。默认是 `critical` 和 `major`。 |
| `minimum_blocking_evidence_band` | 否 | blocking finding 所需的最低证据等级。默认是 `supported`。 |
| `context` | 否 | 收集上下文时的文件大小和 glob 规则。 |

内置维度提示词包括：

- `correctness`：功能缺陷、契约违反、回归和边界情况。
- `security`：授权、注入、secret 暴露及相关安全缺陷。
- `performance`：有实际影响的性能或资源使用失败。
- `architecture`：架构不一致和分层违反。
- `maintainability`：具体且有实际影响的可维护性缺陷。
- `style`：Review Policy 会作为 finding 处理的风格问题。

维度 ID 是字符串，因此也接受自定义 ID；对于未知 ID，系统会使用通用维度提示词。
如果内置维度的关注范围符合需求，建议优先使用内置 ID。

上下文规则：

- merge-candidate diff 是 mandatory context。
- 在 scope 内的变更路径都是 mandatory context，除非被排除。
- `mandatory_globs` 会增加必须存在且可检视的文件。文件缺失、是二进制、超过大小限制、
  不是有效 UTF-8，或者是 Git LFS pointer 时，required coverage 不完整，gate 为 `Error`。
- `optional_globs` 在文件存在时增加文件。缺失的 optional 文件会披露，但不会单独导致
  coverage 不完整。默认 optional 包括 `AGENTS.md` 和 `CLAUDE.md`。
- `excluded_globs` 会从检视上下文中移除匹配路径。它优先于 mandatory 或 optional 的额外匹配。
- `max_file_bytes` 同时适用于收集的文件和 merge-candidate diff，默认是 `1048576` 字节。

仓库指令文件只是上下文数据，不是策略，也不是可信指令。Provider 自行声明的 `verified`
不会被当作独立验证；证据必须先和捕获的 Review Worktree 或其声明的 gathered source
相匹配，才能影响 gate。

### 内置提示词层级

内置提示词在源代码树的 `src/worktree_review/prompts/` 下可见，安装包也会携带这些可信
resource；它们永远不会从被审查仓库加载：

```text
src/worktree_review/prompts/
├── 00-product/role.md
├── 10-safety/untrusted-content.md
├── 20-review/evidence.md
├── 30-dimensions/
│   ├── default.md
│   ├── correctness.md
│   ├── security.md
│   ├── performance.md
│   ├── architecture.md
│   ├── maintainability.md
│   └── style.md
└── 40-output/structured-findings.md
```

每个 dimension 的 system prompt 按以下顺序组合：

1. 产品角色和精确 merge-candidate scope。
2. 不可信内容和工具安全边界。
3. 证据及 provenance 要求。
4. 所选 dimension 的关注范围。
5. 结构化 finding 输出要求。

这些是产品拥有的提示词层，不是仓库指令。可以直接从已安装的 CLI 检查某个 dimension
实际使用的层级：

```bash
worktree-review prompts --dimension security
```

第一阶段还没有提供用户提示词编辑器，也不会从被审查仓库加载 prompt override。

### Advanced Compute Policy

Compute Policy 控制 Provider、model、单次输出上限、传输披露，以及高级部署的每次检视预算。
文档 schema 是 `worktree-review.compute-policy/v1`。

Anthropic 示例：

```yaml
schema: worktree-review.compute-policy/v1
version: 0.1.0
provider: anthropic
model: claude-sonnet-4-5
max_output_tokens_per_call: 8192
max_budget_usd: 2.00
allow_start_under_uncertain_price: false
permit_remote_transmission: true
input_usd_per_million_tokens: 3
output_usd_per_million_tokens: 15
data_destination: https://api.anthropic.com
known_retention: "填写部署所批准的 retention 条款。"
```

字段：

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `schema` | 是 | 必须是 `worktree-review.compute-policy/v1`。 |
| `version` | 是 | 记录在 Attempt 上的语义化版本。 |
| `provider` | 是 | `anthropic` 或 `openai`；本地 command 使用普通 `--config`。 |
| `model` | 是 | 传给所选 Provider SDK 的 model 标识符。 |
| `max_output_tokens_per_call` | 否 | 每次 Provider 调用请求的硬性最大输出；高级策略默认 `8192`。 |
| `max_budget_usd` | 是 | 一次检视允许的最大配置预算。 |
| `allow_start_under_uncertain_price` | 否 | 无法计算价格时是否允许开始。默认是 `false`。 |
| `permit_remote_transmission` | 否 | 是否明确同意把检视上下文发送给 Provider。默认是 `false`。 |
| `input_usd_per_million_tokens` | 否 | 用于预估和成本披露的输入价格。 |
| `output_usd_per_million_tokens` | 否 | 用于预估和成本披露的输出价格。 |
| `data_destination` | 是 | 在发送前披露的、面向人的目的地描述。 |
| `known_retention` | 是 | 随结果披露的、面向人的 retention 信息。 |

使用 `--compute-policy` 执行 live CLI 检视时，只有在目的地和 retention 获得批准后才设置
`permit_remote_transmission: true`。如果是 false，CLI 会在调用 Provider 前拒绝本次调用，
并返回 `3`。最小的 `--config` 形式把配置的远程 Provider/key 或本地 command 视为把内容
交给所选 Provider 的明确同意，但仍会披露本地 command 可能自行联网；未填写 URL 时使用标准
remote endpoint。

对于高级策略，`data_destination` 是披露元数据，不会配置自定义 API endpoint；所选 Provider
SDK 仍使用自己的默认 endpoint。最小 `--config` 中的可选 `url` 会作为实际 Provider endpoint。
`known_retention` 也只是配置中的披露文本，CLI 不会独立验证它。

使用 `--compute-policy` 时，CLI 从环境变量读取远程凭据，不从该 YAML 读取：

| Compute Policy `provider` | 环境变量 |
| --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |

例如：

```bash
export ANTHROPIC_API_KEY='从 secret store 获取的密钥'
```

不要提交 API key。最小的 `--config` 可以包含明文 key，但文件必须受保护且位于被审查
worktree 之外；更推荐使用环境变量引用。`--config` 引用的环境变量缺失属于无效配置，
退出码为 `3`；高级 `--compute-policy` 路径所需的环境变量缺失时，检视为 `Error`，退出码
为 `2`。

普通 `--config` 的 Compute 行为：

- CLI 会在开始 Provider 调用前，为每个 required dimension 做输入 token 预估；普通路径不
  预测美元费用，也不设置 Worktree Review 自己的美元预算。
- 调用开始前，stderr 会显示模型调用次数、预计输入 token，以及每次调用的最大输出 token。
  普通路径的最大输出是 `4096`。
- 完成后，Provider 返回 measured usage 时显示实际用量。只有 Provider 或高级价格策略提供
  成本时才显示费用，否则提示查看 Provider 账户账单。
- 真实支出由 Provider 账户控制；每次调用的硬性输出上限控制普通请求的单次规模。

高级 `--compute-policy` 的预算行为：

- CLI 会在开始 Provider 调用前，为每个 required dimension 做预估。
- 如果希望得到有价格的预估，应同时配置输入和输出价格。需要的价格缺失且
  `allow_start_under_uncertain_price` 为 false 时，检视不会开始。
- required dimensions 按顺序运行，因此已测量的用量可以在剩余预算不足以覆盖下一个预估时
  停止后续调用。
- 可以明确允许未知价格，但结果可能显示未知成本。这个设置不会使成本变得确定，也不会
  授权系统自行假设价格。

## 检视来源

可以在仓库中运行命令，也可以传入 `--repository PATH`。默认仓库是当前目录。

target 是 proposed source 要合入的 commit；proposed source 是 Worktree Review 捕获并检视的内容。

| 调用方式 | Target | Proposed source | 条件 |
| --- | --- | --- | --- |
| 不传 source flag | `HEAD` | 当前 worktree snapshot | 默认行为。 |
| `--target REF` | `REF` | 当前 worktree snapshot | 包含当前更改。 |
| `--commits N` | `HEAD~N` | 当前 worktree snapshot | 检视最近 `N` 次提交加当前更改。不能和 `--target` 或 `--proposed` 同时使用。 |
| `--proposed REF` | 未传 `--target` 时为 `HEAD` | 显式已提交 ref | worktree 必须干净。不能和 `--commits` 同时使用。 |

当前 worktree snapshot 包括：

- tracked 文件当前的字节内容，包括 staged 和 unstaged 更改；
- 未被忽略的 untracked 文件；
- tracked 文件的新增、删除、mode 变化和 symlink。

被忽略的 untracked 文件不会包含在内。snapshot 在 pipeline 开始前捕获一次，Worktree Review
不会修改用户的 index 或 worktree。clean worktree 表示没有当前更改；使用默认 source 时，
此时 proposed head 会解析为当前 `HEAD`。

示例：

检视当前 worktree 与 `HEAD` 的合并结果：

```bash
worktree-review review \
  --config ~/.config/worktree-review/config.yaml
```

检视当前 worktree 合入 `origin/main` 的结果：

```bash
worktree-review review \
  --repository /path/to/repository \
  --target origin/main \
  --config /secure/worktree-review/config.yaml
```

检视最近三次提交加未提交的当前更改：

```bash
worktree-review review \
  --commits 3 \
  --config /secure/worktree-review/config.yaml
```

在 worktree 干净时检视显式提交分支：

```bash
git status --short
worktree-review review \
  --target main \
  --proposed feature/payment-fix \
  --config /secure/worktree-review/config.yaml
```

如果 worktree 有更改，应删除 `--proposed`，让 CLI 检视当前 snapshot。

## 输出和退出码

默认把人类可读输出写到 stdout：

```bash
worktree-review review \
  --config /secure/worktree-review/config.yaml
```

使用 `--format json` 输出有版本的
`worktree-review.cli.result/v1` 文档：

```bash
worktree-review review \
  --format json \
  --config /secure/worktree-review/config.yaml \
  > review-result.json
```

Provider handoff disclosure、调用计划和非权威进度行会在 Provider 调用前及运行期间写到
stderr，因此只重定向 stdout 时仍会得到纯 JSON。如果需要审计 Provider、model、目的地、
retention、本地配置 fingerprint、token 上限或当前阶段/dimension，不要丢弃 stderr。

两种输出格式都会暴露 Attempt ID、Request Key、source 和不可变 head、stage outcomes、
dimension outcomes、findings、draft findings、coverage、usage、call plan、策略版本和
Compute Policy 披露。merge construction 成功时，还会暴露 Merge Candidate Identity 和
Review Identity。

本地 CLI 使用以下进程退出码：

| 码 | 状态 | 含义 |
| ---: | --- | --- |
| `0` | `Passed` | required dimensions 和 coverage 完成，且没有未解决的 blocking finding。 |
| `1` | `Blocked` | 至少有一个依据 Review Policy 阻断的 verified/supported finding。 |
| `2` | `Error` | 检视无法完成，或 Provider、预算、pipeline stage 失败。 |
| `3` | invalid invocation | flag、ref、策略路径、Git 版本、传输同意，或 worktree snapshot 无效/无法表示。 |

CLI 永远不会输出 `Passed with bypass`。draft findings 只用于诊断，不是正式 finding，不能
产生 `Passed` 或 `Blocked`。dimension 未完成、required coverage 不完整或 finding verification
失败时，gate 保持 `Error`。

## 常见问题排查

### 找不到配置或策略文件

传入 `--config PATH`，或者在默认配置目录创建 `config.yaml`。如果使用自定义 Review Policy
或高级 Compute Policy，再显式传入对应 flag。如果 CLI 查找的目录不符合预期，检查
`XDG_CONFIG_HOME`。

### 策略文件位于仓库内

把它移动到可信的用户或部署目录。包括 `AGENTS.md` 和 `CLAUDE.md` 在内的仓库文件，都不能
改变 Review Policy 或 Compute Policy。

### Provider handoff 被拒绝

检查 CLI 打印的传输披露。最小配置中，配置远程 Provider/key 或本地 command 就表示同意把内容
交给所选 Provider。对于本地 command，应检查 command、adapter、目的地和 retention metadata，
因为 Worktree Review 无法证明 command 是否联网。使用高级 Compute Policy 时，只有在 Provider、
目的地和 retention 获得批准后，才设置 `permit_remote_transmission: true`。

### Provider 认证失败

远程 Provider 要检查 `provider`、可选 URL 和 model 是否对应目标 SDK，并确认配置的 key
可用。只有构造所选 Provider 时才会读取 key。本地 Provider 要检查 command 数组中的每一项
都存在且可执行，并确认 adapter 与 command 的 stdin/stdout 行为相符。非零退出和格式错误会
包含有长度限制、控制字符已转义的子进程 stderr/stdout 诊断。

### 高级 budget pre-flight 拒绝开始

这只适用于 `--compute-policy`。提高 `max_budget_usd`，配置输入和输出 token 价格，或者明确
决定是否允许通过 `allow_start_under_uncertain_price: true` 在价格不确定时开始。普通
`--config` 没有 Worktree Review 自己的美元预算，应查看 Provider 账户限制。

### 显式 proposed ref 被拒绝

`--proposed REF` 只用于已提交 source，并要求 worktree 干净。要包含当前更改，删除
`--proposed`；要检视提交范围加当前更改，使用 `--commits N`。

### merge 或 snapshot 构造失败

merge conflict 会返回 `Error`；无法表示的 worktree snapshot 会返回 invalid invocation。解决
冲突或不支持的 filesystem entry 后重新运行。CLI 不会为了这个过程执行或修改 proposed code。

### 结果是 `Error`

检查 `stage_outcomes`、`dimension_outcomes`、`coverage`、`error_detail` 和 terminal 输出中的
`Error:` 行。部分结果可能包含已验证 findings 和可见 draft findings，但它不是 Passed 或 Blocked
gate 决定。

## Server 状态

server 入口需要 server extra：

```bash
uv sync --extra server
```

当前开发 runtime 识别以下部署变量：

- `WORKTREE_REVIEW_GITHUB_WEBHOOK_SECRET`
- `WORKTREE_REVIEW_DATABASE_URL`
- `WORKTREE_REVIEW_GITHUB_TOKEN`
- `WORKTREE_REVIEW_REVIEW_POLICY_PATH`
- `WORKTREE_REVIEW_GITHUB_API_URL`（可选，默认 `https://api.github.com`）

`GET /healthz` 可作为 liveness endpoint。webhook 和 retry state 部分已经存在，但内置 review
worker 以及端到端 shared pipeline publication 仍未完成。当前应把上面的本地 CLI 作为支持的
用户工作流；部署 server 作为检视服务前，先完成 GitHub worker。

## 进一步阅读

- [用户配置示例](config.example.yaml)
- [Review Policy 示例](examples/review-policy.yaml)
- [高级 Compute Policy 示例](examples/compute-policy.yaml)
- [产品要求](docs/PRD.zh-CN.md)
- [技术设计](docs/TECH-DESIGN.zh-CN.md)
