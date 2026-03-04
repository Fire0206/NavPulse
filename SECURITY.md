# 安全策略 | Security Policy

## 支持的版本 | Supported Versions

当前项目处于积极维护状态，建议使用最新版本以获得最新的安全更新。

| 版本 | 支持状态 |
| ------- | ------------------ |
| 5.0.x   | :white_check_mark: |
| < 5.0   | :x:                |

## 安全最佳实践 | Security Best Practices

### 部署前必须配置

1. **JWT 密钥配置**（生产环境强制要求）
   ```bash
   # 在 .env 文件中设置固定密钥
   JWT_SECRET_KEY=<生成的随机密钥>
   ENVIRONMENT=production
   ```
   
   生成强密钥示例：
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **CORS 白名单**
   ```bash
   # 仅允许特定域名访问（逗号分隔）
   CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
   ```

3. **HTTPS 强制**
   - 生产环境必须启用 HTTPS
   - 应用会在 `ENVIRONMENT=production` 时自动添加 HSTS 响应头

### 密码要求

- **最少 8 位字符**
- 必须包含：大写字母、小写字母、数字
- 建议：包含特殊字符以提升强度

### 速率限制

- 登录接口：5 分钟内最多 5 次失败尝试
- 超限后需等待 5 分钟
- 基于 IP + 用户名组合计算

### 数据库安全

- 密码使用 bcrypt 单向哈希存储
- SQLite 启用 WAL 模式，定期备份 `app/data/navpulse.db`
- 生产环境建议迁移到 PostgreSQL/MySQL

### 环境变量说明

```bash
# 认证相关
JWT_SECRET_KEY=<必填，生产环境>
TOKEN_EXPIRE_MINUTES=1440  # Token 有效期（分钟），默认 24h
ENVIRONMENT=production      # 启用生产模式安全策略

# CORS 安全
CORS_ORIGINS=*             # 开发模式可用 *，生产必须指定域名

# ICP 备案号（可选）
ICP_RECORD=京ICP备xxxxxxxx号
```

## 报告安全漏洞 | Reporting Security Issues

**请勿在公开 Issue 中报告安全漏洞！**

如发现安全问题，请通过以下方式私密报告：

1. 使用 GitHub Security Advisories（推荐）
   - 进入仓库 → Security → Report a vulnerability

2. 通过邮件联系维护者
   - 请在邮件主题标注 `[SECURITY]`
   - 详细描述漏洞复现步骤和影响范围

我们会在 48 小时内响应，并在修复后公开致谢（除非您要求匿名）。

## 安全响应时间 | Response Timeline

- **关键漏洞**（RCE、SQL 注入等）：24 小时内修复
- **高危漏洞**（认证绕过、数据泄露）：48 小时内修复
- **中危漏洞**：7 天内修复
- **低危漏洞**：下一个版本修复

## 已知限制 | Known Limitations

1. **速率限制基于内存缓存**：重启服务会清空速率限制计数器
2. **SQLite 并发限制**：高并发场景（>100 用户）建议迁移到 PostgreSQL
3. **第三方数据源**：依赖 akshare 和腾讯股票接口，数据准确性取决于上游

## 安全更新日志 | Security Changelog

### 2026-03-04 | v5.0.0

- ✅ 增强密码强度要求（8 位 + 大小写 + 数字）
- ✅ 添加登录速率限制（防暴力破解）
- ✅ 实现安全响应头（HSTS、CSP、X-Frame-Options 等）
- ✅ 模糊化认证错误提示（防用户名枚举）
- ✅ 生产环境 SECRET_KEY 强制检查

---

**感谢您帮助 NavPulse 保持安全！**
