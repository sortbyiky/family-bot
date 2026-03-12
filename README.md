# Family Bot

家庭组自动化管理工具，支持 Web 界面和 CLI 命令行两种操作方式。

自动完成：Google 账号登录 → Gemini 开通 → 家庭组邀请接受 → Antigravity OAuth 授权。

## 环境要求

- Python 3.10+
- Linux / macOS / Windows
- Playwright Chromium（自动下载，无需本机安装 Chrome）

## 部署（服务器推荐）

```bash
# 克隆项目
git clone https://github.com/sortbyiky/family-bot.git
cd family-bot

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Playwright Chromium 驱动
playwright install chromium
```

### systemd 服务（推荐，开机自启）

创建 `/etc/systemd/system/family-bot.service`：

```ini
[Unit]
Description=Family Bot Web Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/family-bot
Environment=BROWSER_HEADLESS=true
Environment=BROWSER_SLOW_MO=100
Environment=BROWSER_CHANNEL=chromium
Environment=WEB_HOST=0.0.0.0
Environment=WEB_AUTH_PASSWORD=你的密码
ExecStart=/usr/bin/python3 run_web.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable family-bot
systemctl start family-bot
```

### 常用命令

```bash
systemctl status family-bot   # 查看状态
systemctl restart family-bot  # 重启服务
journalctl -u family-bot -f   # 实时日志
```

## 启动（本地开发）

```bash
python run_web.py
```

浏览器访问 http://localhost:5000

## 访问与安全

- Web 界面支持**密码登录**（无需用户名）
- 登录后可在导航栏「改密」入口修改密码
- 密码持久化存储在 `data/password.txt`，重启服务不丢失
- 优先级：`data/password.txt` > 环境变量 `WEB_AUTH_PASSWORD`

## 使用流程

### 1. 添加家长账号

进入「家长管理」页面，添加家庭组家长的 Google 邮箱和密码。

### 2. 添加成员账号

进入「成员管理」页面，选择所属家长，填入成员邮箱、密码、TOTP 密钥（2FA 必填）。

支持批量导入，格式：

```
邮箱----密码----TOTP密钥
```

### 3. 执行自动化任务

进入「任务管理」页面，支持全量执行、按家长执行、按成员执行。

自动化流程依次完成：

1. **Google 登录** — 使用成员邮箱密码登录，支持 2FA
2. **Gemini 开通** — 自动访问 Gemini 并完成激活
3. **家庭组加入** — 在 Gmail 中查找邀请邮件并接受

成员状态流转：`pending` → `gemini_done` → `joined`

任务页每 3 秒自动刷新，任务失败会通过 Telegram 通知。

### 4. Antigravity OAuth（可选）

成员状态为 `joined` 后可用：

1. 在成员列表顶部粘贴 OAuth 链接
2. 点击对应成员的「Antigravity」按钮
3. 自动完成 OAuth 授权，回调 URL 写入备注栏
4. 点击「复制」按钮获取回调 URL

## CLI 命令参考

```bash
# 家长管理
python main.py parent add --email xxx@gmail.com --password xxx
python main.py parent list

# 成员管理
python main.py member add --parent-id 1 --email xxx@gmail.com --password xxx
python main.py member list

# 执行任务
python main.py run member <member_id>
python main.py run parent <parent_id>
python main.py run all

# 查看状态
python main.py status
```

## 项目结构

```
family-bot/
├── automation/          # 自动化脚本
│   ├── google_login.py      # Google 账号登录
│   ├── gemini_activate.py   # Gemini 开通激活
│   ├── family_accept.py     # 家庭组邀请接受
│   ├── antigravity_login.py # Antigravity OAuth 登录
│   └── appeal_form.py       # 申诉表单自动填写
├── cli/                 # CLI 命令行工具
├── web/                 # Web 管理界面（Flask）
│   ├── routes/              # 路由（家长、成员、任务、认证）
│   ├── templates/           # 页面模板
│   └── task_manager.py      # 后台任务管理
├── db/                  # 数据库（SQLAlchemy + SQLite）
├── data/                # 运行时数据（自动生成，gitignore）
│   ├── family_bot.db        # SQLite 数据库
│   ├── password.txt         # 登录密码（Web 改密后写入）
│   ├── chrome_profiles/     # 成员独立 Chrome 配置
│   └── screenshots/         # 自动化过程截图
├── config.py            # 全局配置
├── run_web.py           # Web 服务入口
├── main.py              # CLI 入口
└── requirements.txt     # Python 依赖
```

## 配置说明

所有配置项均支持环境变量覆盖：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BROWSER_HEADLESS` | `false` | 服务器部署建议设为 `true` |
| `BROWSER_SLOW_MO` | `100` | 操作间隔（毫秒） |
| `BROWSER_CHANNEL` | `chrome` | 浏览器类型，服务器用 `chromium` |
| `WEB_HOST` | `127.0.0.1` | 监听地址，公网访问设为 `0.0.0.0` |
| `WEB_PORT` | `5000` | 监听端口 |
| `WEB_AUTH_PASSWORD` | 无 | 访问密码，为空则不需要登录 |
| `MAX_CONCURRENT_TASKS` | `5` | 最大并发任务数 |

## 数据持久化

`data/` 目录已被 `.gitignore` 排除，git 操作不会影响运行时数据。

推荐使用 `git pull` 方式更新代码，数据目录完全不受影响。

### 迁移服务器

```bash
# 1. 在旧服务器备份数据
cp -r /root/family-bot/data/ ~/family-bot-data-backup/

# 2. 在新服务器部署完成后还原数据
cp -r ~/family-bot-data-backup/ /root/family-bot/data/
```

> ⚠️ `data/` 目录包含所有账号数据（已加密存储）和登录密码，迁移时务必一并转移。

## 注意事项

- 每个成员使用独立的 Chrome Profile，互不干扰
- 首次运行时 `data/` 目录会自动创建
- 服务器部署必须开启 `BROWSER_HEADLESS=true`，否则无显示器会报错
- 执行自动化任务时请勿手动操作浏览器
