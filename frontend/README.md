# Worktree Review frontend

React + TypeScript Vite app for the Worktree Review Web UI.

## Scripts

```bash
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run preview -- --host 127.0.0.1
```

`test` is `vitest run` (non-watch). `test:e2e` is `playwright test`. Preview binds loopback only.
