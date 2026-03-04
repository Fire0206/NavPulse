# Contributing Guide

感谢你为 NavPulse 做贡献。为保证代码可维护、可部署、可开源协作，请遵循以下规范。

## 1) 项目结构约定

- `app/routers/`: 仅放 API 路由与参数校验，不写重业务逻辑。
- `app/services/`: 业务逻辑层，优先无副作用、可复用函数。
- `app/static/js/components/`: 前端页面组件（PascalCase 命名）。
- `app/static/js/`: 通用能力（`api.js` / `store.js` / `utils.js`）。
- `app/static/css/`: 全局主题与样式。
- `app/templates/`: Jinja2 模板（入口 HTML）。
- `docs/`: 设计/算法/部署文档。
- `scripts/`: 一次性或维护脚本（snake_case 命名）。

## 2) 命名规范

- Python 文件/函数/变量: `snake_case`
- Python 类名: `PascalCase`
- 前端组件文件: `PascalCase.js`
- 常量: `UPPER_SNAKE_CASE`
- API 路径: 统一使用小写 + `kebab-case` 或已有风格，避免混用

## 3) 代码规范与提交前检查

### 安装开发工具

```bash
pip install -r requirements-dev.txt
pre-commit install
```

### 本地检查

```bash
ruff check app scripts
ruff format app scripts
black app scripts
isort app scripts
```

> 已在仓库提供 `.editorconfig`、`pyproject.toml` 与 `.pre-commit-config.yaml`。

## 4) 提交流程建议

- 单次 PR 聚焦一个主题（UI、估值算法、部署等）。
- 提交信息建议：
  - `feat(scope): ...`
  - `fix(scope): ...`
  - `refactor(scope): ...`
  - `docs(scope): ...`
  - `chore(scope): ...`
- 变更涉及行为变化时，请同步更新：
  - `README.md`
  - `PROJECT_SUMMARY.md`
  - `DEPLOY.md`（如部署流程受影响）

## 5) 安全与开源注意事项

- 严禁提交 `.env`、密钥、真实数据库文件。
- 仅提交 `.env.example` 作为配置模板。
- 对外发布前请确认 `SECURITY.md` 与免责声明保持最新。

## 6) 部署前最小检查清单

- `ENVIRONMENT=production`
- 设置强随机 `JWT_SECRET_KEY`
- `CORS_ORIGINS` 改为正式域名
- 反向代理启用 HTTPS
- 运行一次 `ruff check` + 启动自测
