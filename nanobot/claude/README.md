# Claude Code 集成文档

本文档介绍 nanobot 与 Claude Code 的集成功能，让你可以通过各种聊天平台直接与 Claude Code 对话。

## 目录

- [快速开始](#快速开始)
- [连接手机与服务器](#连接手机与服务器)
- [基础命令](#基础命令)
- [会话管理](#会话管理)
- [功能列表](#功能列表)
- [建议新增的功能](#建议新增的功能)

---

## 快速开始

### 1. 配置 Claude Code

在 `~/.nanobot/config.json` 中启用 Claude Code：

```json
{
  "claudeCode": {
    "enabled": true,
    "claude_path": "claude",
    "default_model": "sonnet",
    "max_sessions_per_user": 10
  }
}
```

### 2. 启动服务

```bash
nanobot gateway
```

### 3. 开始对话

在支持的聊天平台（飞书、Telegram、Discord 等）发送消息即可与 Claude Code 对话。

---

## 连接手机与服务器

### 方式一：飞书（Lark/Feishu）

1. 创建飞书企业应用
2. 配置应用凭证（App ID 和 App Secret）
3. 在飞书配置中启用机器人
4. 将应用添加到群聊或私聊

配置文件示例：
```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "app_id": "your_app_id",
      "app_secret": "your_app_secret"
    }
  }
}
```

### 方式二：Telegram

1. 创建 Telegram Bot（通过 @BotFather）
2. 获取 Bot Token
3. 配置 nanobot

配置文件示例：
```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "your_bot_token"
    }
  }
}
```

### 方式三：Discord

1. 创建 Discord 应用
2. 添加机器人到服务器
3. 获取 Bot Token

配置文件示例：
```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "your_bot_token"
    }
  }
}
```

### 方式四：其他平台

nanobot 还支持：Slack、WhatsApp、钉钉、Email 等多种渠道。

---

## 基础命令

### Claude Code 开关

| 命令 | 说明 |
|------|------|
| `/claude on` | 启用 Claude Code 模式 |
| `/claude off` | 禁用 Claude Code，切换到 nanobot agent 模式 |
| `/claude` | 查看当前状态 |

### 快捷命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `?` | 显示帮助信息 |

---

## 会话管理

### 创建新会话

```
/session new
# 或
/new
```

### 列出会话

```
/session list
# 或
/list
```

### 切换会话

```
/session switch <编号>
# 或
/switch <编号>
```

### 关闭当前会话

```
/session close
# 或
/close
```

### 关闭所有会话

```
/session closeall
# 或
/closeall
```

---

## 功能列表

### 已实现的功能

1. **多平台支持**
   - 飞书、Telegram、Discord、Slack、WhatsApp、钉钉、Email 等

2. **Claude Code 集成**
   - 直接调用 Claude Code 进行对话
   - 支持流式输出（实时显示响应）

3. **会话管理**
   - 多会话支持（最多 10 个/用户）
   - 会话持久化（保存在磁盘）
   - 随时切换会话

4. **模式切换**
   - `/claude on` - Claude Code 模式
   - `/claude off` - nanobot agent 模式

5. **配置选项**
   - 自定义 Claude CLI 路径
   - 选择默认模型
   - 限制可用工具
   - MCP 服务器集成

### 支持的消息类型

- 文本消息
- 图片消息（会下载并上传给 Claude Code）
- 文件消息
- @机器人消息

---

## 建议新增的功能

### 高优先级

1. **上下文记忆增强**
   - 支持更长的上下文窗口
   - 自动摘要长对话

2. **语音消息支持**
   - 语音转文字后发送给 Claude Code
   - Claude Code 回复转语音（Text-to-Speech）

3. **多模态对话**
   - 支持发送图片给 Claude Code 分析
   - 支持文件上传和解析

4. **会话导出/导入**
   - 导出对话记录为 Markdown
   - 导入已有对话继续

### 中优先级

5. **Web Search 集成**
   - 让 Claude Code 可以搜索互联网
   - 实时获取最新信息

6. **代码执行环境**
   - 在沙箱中执行代码
   - 返回执行结果

7. **定时任务**
   - 定期调用 Claude Code 执行任务
   - 定时报告或摘要

8. **群聊 @指定回复**
   - 只回复 @机器人的消息
   - 识别并忽略无关消息

### 低优先级

9. **自定义提示词**
   - 为不同用户/群组设置不同的系统提示词
   - 支持预设角色

10. **Webhook 集成**
    - 接收外部系统的消息
    - 向外部系统发送通知

11. **对话翻译**
    - 自动翻译用户消息给 Claude Code
    - 翻译 Claude Code 回复

12. **敏感词过滤**
    - 自定义敏感词列表
    - 自动过滤或警告

---

## 常见问题

### Q: Claude Code 是什么？

Claude Code 是 Anthropic 推出的 CLI 工具，可以在终端中与 Claude AI 对话，支持执行命令、读写文件等操作。

### Q: 如何查看当前 Claude Code 状态？

发送 `/claude` 即可查看当前是开启还是关闭状态。

### Q: 为什么发送消息没有回复？

1. 检查 Claude Code 是否启用：发送 `/claude` 查看状态
2. 如果是关闭状态，发送 `/claude on` 开启
3. 检查 nanobot 服务是否正常运行

### Q: 如何切换到 nanobot agent 模式？

发送 `/claude off` 即可切换回 nanobot 自带的 agent 模式。

### Q: 会话丢失了怎么办？

会话会持久化到磁盘，重新发送消息会自动恢复之前的会话。如需全新会话，使用 `/session new`。

---

## 相关文件

- `nanobot/claude/handler.py` - 消息处理器
- `nanobot/claude/router.py` - 会话路由
- `nanobot/claude/client.py` - Claude Code 客户端
- `nanobot/claude/session.py` - 会话管理
