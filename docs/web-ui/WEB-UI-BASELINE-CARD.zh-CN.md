# Web UI 基线任务卡（PM-001）

- 状态：已建立
- 建立时间：2026-09-09
- Base commit：`fe574b9beebe6735da016a7f143f356adfb18cca`（`fe574b9`）
- 说明：相对任务书写定时的 `08604ad` dirty tree，既存修改已由 `83a2478` + `6f63aea` 落盘。在此之上增加忽略 `.worktrees/` 的运维提交，使集成分支工作区保持干净。

## 分支与 Worktree

| 角色 | 分支 | 工作目录 |
| --- | --- | --- |
| Integration / PM | `integration/web-ui` | `/home/deck/projects/worktree-review` |
| Agent A | `agent-a/web-ui` | `/home/deck/projects/worktree-review/.worktrees/agent-a` |
| Agent B | `agent-b/web-ui` | `/home/deck/projects/worktree-review/.worktrees/agent-b` |
| 参考保留 | `master` | 仍指向 `6f63aea`（产品文档落盘点；未单独 checkout） |

约束：Agent A/B 不得共用 Integration checkout；开工前须能报告与 Integration 相同的 base commit。

## 工作文档

- `.ai-docs/` 被 `.gitignore` 忽略，不入库。
- Agent A/B worktree 通过符号链接共享主仓 `.ai-docs/`。
- 因 `/home/deck/projects/` 与家目录顶层不可新建目录，Agent worktree 放在仓库内 `.worktrees/`（已忽略）。

## 下一步

1. PM-002：发布 G0 契约包（路由、View Model、Fixture、Token、依赖清单）。
2. 之后才可派发 A-001。
