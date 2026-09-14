# Worktree Review Web UI 演示包（PM-011）

- 状态：可用于 2026-09-10 演示
- 基线：`integration/web-ui`，集成 HEAD `337959b`
- 范围：P0 高保真原型（Dashboard + Review Detail 七标签页 + 三类可重复 Case）
- 配套截图：`frontend/qa/pm011/`；离线验证记录：`frontend/qa/pm011/offline-preview.txt`

## 1. 启动说明（离线可演示）

一次性准备（仅此步需要网络，访问 npm registry）：

```bash
npm --prefix frontend ci
```

构建与启动（构建后运行完全离线）：

```bash
npm --prefix frontend run build
npm --prefix frontend run preview -- --host 127.0.0.1
```

浏览器打开 `http://127.0.0.1:4173`（自动重定向到 `/overview`）。

- Preview 只绑定 loopback；运行时不请求 registry、CDN、Provider、GitHub 或任何外网资源。
- 全部数据来自构建产物内置的 Fixture 与录制的本地 Pipeline Snapshot（`MockReviewDataSource`）。
- 验证证据：`frontend/qa/pm011/offline-preview.txt`（四条演示路由均 200；dist 无运行时外部
  请求目标；e2e 用 request 监听断言 Detail 交互零远程请求）。

## 2. 三类演示 Case 与固定入口

| Case | 固定入口（URL） | 来源类型 | 数据性质 |
| --- | --- | --- | --- |
| Blocked | `/reviews/attempt_01JY8R7F2W` | GitHub PR（`acme/payment-service` #184） | 手写产品 mock |
| Passed | `/reviews/attempt_01JY8P4SS0D` | Local（`acme/session-insight`） | 手写产品 mock |
| Error（merge conflict） | `/reviews/attempt_01JY8E4R0R` | Local committed ref（`acme/demo-invalid-config`） | 手写产品 mock |

右上角 **Demo case** 选择器是唯一的 Case 切换入口；带 `Pipeline snapshot ·` 前缀的三个条目是
A-015 从真实本地 Pipeline 录制并经 Schema 校验的快照，与手写 mock 明确区分，不得混讲。

## 3. 固定点击脚本

预计 8–10 分钟。每一步列出操作与必须讲到的可观测结果。

1. **Dashboard 首屏**：打开 `/overview`。全局横幅 `Mock data · Pre-Alpha`；默认深色主题。
   `Needs attention` 先于统计图表出现：Blocked（PR #184，3 findings · 2m 18s · $0.42）与
   Error（本地 committed ref，成本 Unknown）。截图 `01-dashboard-needs-attention.png`。
2. **进入 Blocked Detail**：点击 Blocked 行。来源自适应 Header 显示 GitHub PR、
   `Authoritative attempt`（图标+文字+颜色三重编码）、`feature/webhook-auth → main`、
   Policy 1.3.0、openai / gpt-5.6、$0.42。Merge candidate path 全部完成，明确表达
   “检视的是 target 与 proposed 的精确合并结果”。截图 `02-blocked-detail-overview.png`。
3. **Findings → Evidence**：切到 Findings，勾选 `Blocking only` → `1 of 3 findings`；选择
   blocking Finding（签名 Header 缺失时 fallback 仍接受请求）。Evidence 面板高亮引用行
   （`return True` 接受分支），展示 verified quoted source、fingerprint、repair guidance；
   界面只有 guidance，没有任何自动修改按钮。截图 `03-blocked-findings-evidence.png`。
4. **Coverage**：`Complete` 但展开为 48 reviewed · 0 missing · 2 excluded——不用单一百分比
   掩盖缺失。
5. **Attempts**：`Current attempt` 标识与权威关系。截图 `04-blocked-attempts.png`。
6. **Identity & Provenance**：`github:acme/payment-service#184` 身份与快照 provenance。
7. **动作能力说明**：Header 操作区 Retry / Bypass / Open Check / Open Session Insight 均为
   禁用态，悬停或键盘聚焦显示禁用原因（Pre-Alpha 未接通 / 本地单用户无 GitHub actor）。
   强调：原型点击这些按钮**不会发出任何远程请求**（e2e 已断言）。
8. **Error Case**：Demo case 选择器 → `Mock data · Error merge conflict`。Pipeline 停在
   `Construct Merge`，光流中止并显示安全失败摘要；无 Bypass 按钮；Identity 明确显示
   “merge candidate 未构造，身份不可用”，不伪造 Review Identity。截图
   `06-error-merge-conflict-detail.png`。
9. **Passed Case**：选择器 → Passed 本地 Case。Local source Header 不出现 PR/Author 字段；
   `Local one-shot result`，明确不触碰 GitHub standing decision。截图
   `05-passed-local-detail.png`。
10. **主题**：右上角切换 Light / System，选择持久化（刷新保持）；状态始终图标+文字+颜色，
    不只依赖颜色。
11. **收尾**：说明 `Pipeline snapshot ·` 条目来自真实本地 Pipeline 录制（A-015），是正式
    演示结果快照；手写 mock 仅用于展示未来 GitHub 产品形态。

## 4. 截图清单（`frontend/qa/pm011/`）

| 文件 | 内容 | 脚本步骤 |
| --- | --- | --- |
| `01-dashboard-needs-attention.png` | Dashboard 首屏，Needs attention 优先 | 1 |
| `02-blocked-detail-overview.png` | Blocked Detail Overview + 九阶段 Pipeline | 2 |
| `03-blocked-findings-evidence.png` | Blocking 筛选 + Evidence 高亮 | 3 |
| `04-blocked-attempts.png` | Attempts 权威标识 | 5 |
| `05-passed-local-detail.png` | Passed 本地 Case | 9 |
| `06-error-merge-conflict-detail.png` | Error merge conflict，Pipeline 中止 | 8 |

重新生成：`npm --prefix frontend run test:e2e -- e2e/demo-package.spec.ts`（深色 1440×900，
全页截图）。Dashboard 双主题×三分辨率矩阵见 `frontend/qa/a014/`。

## 5. 已知限制清单（演示口径）

- **无真实后端**：本地 Review API、SQLite Run Store、SSE 均为 P1；本原型不创建真实 Attempt。
- **Preview 能力**：New Review、Repositories、Policies、Providers、Session Insight、GitHub
  导航入口为 Preview 禁用态，附可访问说明；不是无响应按钮。
- **Retry/Bypass**：P0 只交付目标文案、能力状态与禁用原因；确认对话框与动画在 P0.5（B-014）。
- **远程状态**：Provider health 为最后观测值（页面明示"非实时探测"）；GitHub Checks 与
  Session Insight 未连接并有对应说明；页面不暗示任何未接通能力已正式可用。
- **Attempts 动画**：Authoritative/Superseded/Retry 完整时间轴动画在 P0.5。
- **分辨率**：P0 验证 1280×800 / 1366×768 / 1440×900；平板与移动端深度 QA 在 P0.5。
- **CI**：Frontend CI 接线为 PM-012（P0.5）；当前由 PM 在合并前手工执行 Gate。
- **Python 基线**：`mypy` 存在 10 个既有错误（`server`/`platform/github`，server extras
  未安装所致），`tests/platform/**` 需 PostgreSQL；均与 Web UI 原型无关且在基线上即如此。

## 6. 演示降级顺序（如现场时间不足）

按任务书第 8 节执行：先砍 Recharts 图表讲解，再砍动效，保留 Gate / Finding / Evidence /
Coverage / Attempt authority / 三 Case / 主题，不得牺牲可信度表述。
