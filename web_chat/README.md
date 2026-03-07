# Nanobot Web Chat

公司内共享使用的 Nanobot AI 对话 Web 界面。

## 功能特性

- 用户认证系统（ID + 密码登录）
- 管理员管理允许用户 ID 列表
- 独立对话上下文（每个人有自己的 Soul.md, memory.md, HISTORY.md）
- 团队共享 skills
- 类似 ChatGPT 的 Web 聊天界面
- 流式输出支持

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn python-multipart jinja2 aiofiles itsdangerous
```

### 2. 配置

复制并编辑 `config.example.json` 为 `config.json`:

```json
{
  "allowed_ids": ["user1", "user2", "user3"],
  "admin_ids": ["admin"],
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "session_secret": "change-this-secret-key-in-production"
  },
  "nanobot": {
    "path": "~/.nanobot/nanobot",
    "config_path": "~/.nanobot/config.json",
    "workspace_path": "~/.nanobot/workspace"
  }
}
```

### 3. 启动

```bash
python main.py
```

访问 http://localhost:8000/chat

---

## 从零搭建指南

如果你想从零开始搭建一个组内共享的 Nanobot 个人机器人，按以下步骤操作：

### 步骤 1: 准备 Nanobot

1. 确保已有 Nanobot 项目（或 clone 一个）：
   ```bash
   git clone https://github.com/your-repo/nanobot.git ~/.nanobot/nanobot
   ```

2. 准备 Nanobot 配置文件 `~/.nanobot/config.json`：
   ```json
   {
     "providers": {
       "openai": {
         "api_key": "your-api-key"
       }
     },
     "agents": {
       "defaults": {
         "model": "gpt-4o",
         "temperature": 0.7,
         "max_tokens": 4096,
         "max_tool_iterations": 50,
         "memory_window": 10
       }
     },
     "tools": {
       "web": {
         "search": {
           "api_key": ""
         }
       },
       "exec": {
         "enabled": true
       },
       "restrict_to_workspace": true
     }
   }
   ```

### 步骤 2: 部署 Web Chat

1. 克隆或复制 web_chat 项目到服务器：
   ```bash
   git clone https://github.com/your-repo/web_chat.git
   cd web_chat
   ```

2. 创建配置文件 `config.json`：
   ```json
   {
     "allowed_ids": ["alice", "bob", "charlie"],
     "admin_ids": ["admin"],
     "server": {
       "host": "0.0.0.0",
       "port": 8000,
       "session_secret": "生成一个随机字符串"
     },
     "nanobot": {
       "path": "~/.nanobot/nanobot",
       "config_path": "~/.nanobot/config.json",
       "workspace_path": "~/.nanobot/workspace"
     }
   }
   ```

3. 安装依赖：
   ```bash
   pip install fastapi uvicorn python-multipart jinja2 aiofiles itsdangerous
   ```

4. 启动服务：
   ```bash
   python main.py
   ```

### 步骤 3: 配置说明

| 配置项 | 说明 |
|--------|------|
| `allowed_ids` | 允许注册的用户 ID 列表，留空则允许所有人注册 |
| `admin_ids` | 管理员 ID 列表 |
| `server.host` | 监听地址，`0.0.0.0` 允许外部访问 |
| `server.port` | 监听端口 |
| `server.session_secret` | Session 加密密钥，生产环境请使用随机字符串 |
| `nanobot.path` | Nanobot 代码路径 |
| `nanobot.config_path` | Nanobot 配置文件路径 |
| `nanobot.workspace_path` | Nanobot 工作区路径 |

### 步骤 4: 用户使用

1. 访问 `http://your-server:8000/`
2. 点击"注册新账号"，使用 `allowed_ids` 中的 ID 注册
3. 登录后即可与 Nanobot 对话
4. 每个用户的对话历史会保存在 `users/{user_id}/` 目录下

### 进阶配置

- **修改允许用户**: 编辑 `config.json` 中的 `allowed_ids` 数组
- **自定义机器人性格**: 编辑 `users/{user_id}/soul.md`
- **团队共享 Skills**: 在 `shared_skills/` 目录下添加 skill 文件

## 目录结构

```
web_chat/
├── config.example.json    # 配置文件示例
├── config.json            # 运行时配置
├── main.py               # 主程序入口
├── app/
│   ├── __init__.py
│   ├── app.py           # FastAPI 应用
│   ├── auth.py          # 认证系统
│   ├── chat.py          # 聊天逻辑
│   └── templates/       # HTML 模板
│       ├── login.html
│       ├── register.html
│       └── chat.html
├── users/               # 用户数据目录（运行时生成）
│   └── {user_id}/
│       ├── soul.md      # 机器人性格配置
│       ├── memory/
│       │   ├── MEMORY.md     # 长期记忆
│       │   └── HISTORY.md    # 对话历史
│       └── sessions/    # 会话数据
└── shared_skills/       # 团队共享 skills
```
