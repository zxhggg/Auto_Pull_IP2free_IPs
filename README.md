# IP2FREE Agent

这是一个 Python 脚本，用来登录 IP2FREE、自动领取可领取的活动奖励、拉取免费代理和活动奖励代理，并导出 `yaml` 或 `txt` 格式的代理文件。

### 功能特点
- 从 `.env` 文件读取全部配置
- 在拉取代理前自动领取可直接领取的活动奖励
- 支持分页拉取免费代理
- 拉取活动奖励代理并合并进最终 Clash 配置
- 支持自定义输出目录
- 输出信息清晰，出错时方便排查

### 环境要求
- Python 3.9 及以上
- `requests`

### 安装
```bash
pip install -r requirements.txt
```

### 配置方法
1. 复制模板文件：
```bash
cp .env.example .env
```

Windows 也可以直接复制同目录下的 `.env.example`，然后重命名为 `.env`。

2. 编辑 `.env`：
```dotenv
IP2FREE_EMAIL=your-email@example.com
IP2FREE_PASSWORD=your-password
IP2FREE_CONFIG_PATH=./output
IP2FREE_AUTO_CLAIM_REWARDS=true
IP2FREE_PROXY_SOURCE=both
IP2FREE_OUTPUT_FORMAT=yaml
IP2FREE_ACTIVITY_TASK_NAME_CONTAINS=
```

### 配置项说明
- `IP2FREE_EMAIL`：IP2FREE 登录邮箱
- `IP2FREE_PASSWORD`：IP2FREE 登录密码
- `IP2FREE_CONFIG_PATH`：输出目录，留空时默认输出到桌面 `proxy` 文件夹
- `IP2FREE_AUTO_CLAIM_REWARDS`：是否自动领取可直接领取的活动奖励
- `IP2FREE_PROXY_SOURCE`：代理来源，可选 `free` / `activity` / `both`
- `IP2FREE_OUTPUT_FORMAT`：导出格式，可选 `yaml` / `txt`
- `IP2FREE_ACTIVITY_TASK_NAME_CONTAINS`：只自动领取任务名包含指定文本的任务；留空表示不筛选

`txt` 导出格式示例：
```text
socks5://31.58.9.4:6077:qinlboxi:13txp426eu8r
```
一行一个代理。

### 使用方法
```bash
python ip2free_agent.py
```

### GitHub Actions
仓库里已经带了 `.github/workflows/ip2free_daily.yml`。

如果你要在 GitHub 上自动跑，先配置：
- Repository Variable：`IP2FREE_EMAIL`
- Repository Secret：`IP2FREE_PASSWORD`

workflow 会在运行时临时生成 `.env` 文件，然后执行脚本。
