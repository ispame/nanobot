# Xiaomi 小爱音响接入指南

将小爱音响接入 nanobot，实现语音对话和智能响应。

## 功能特性

- **语音输入**：通过"让小茹箩"触发词唤醒 nanobot，其他语音由小爱正常处理
- **TTS 语音回复**：简单问题直接通过小爱音响语音播放
- **飞书复杂响应**：复杂内容（长文本、代码、表格）自动转发到飞书发送卡片
- **自动 Token 刷新**：无需手动管理 `.mi.json`，配置环境变量即可自动登录和刷新

## 快速开始

### 方式一：使用环境变量自动登录（推荐）

#### 步骤 1：配置环境变量

在项目根目录创建 `.env` 文件（不提交到版本控制）：

```bash
# 复制示例配置
cp nanobot/.env.example nanobot/.env

# 编辑配置，填入你的小米账号信息
# XIAOMI_USER_ID: 小米数字 ID
# XIAOMI_PASSWORD: 密码
# XIAOMI_DID: 设备 ID（可选）
```

`.env` 文件内容：
```bash
XIAOMI_USER_ID=你的小米数字ID
XIAOMI_PASSWORD=你的密码
XIAOMI_DID=你的设备ID
```

#### 步骤 2：配置 nanobot

在 `~/.nanobot/config.json` 中添加：

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "deviceName": "小爱音箱",
      "triggerKeywords": ["让小茹箩"],
      "feishuReplyEnabled": true,
      "allowFrom": ["default"]
    }
  }
}
```

#### 步骤 3：运行

```bash
nanobot gateway
```

启动时 nanobot 会：
1. 读取 `.env` 中的凭据
2. 自动登录获取 `serviceToken`
3. 生成 `.mi.json` 文件
4. Token 过期时自动重新登录

---

### 方式二：手动配置 .mi.json

如果你已有 `.mi.json` 文件（通过 migpt-next 生成），可以直接使用：

```bash
# 1. 复制 .mi.json 到项目根目录
cp /path/to/.mi.json .

# 2. 配置 nanobot
```

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "miotConfigPath": "/path/to/.mi.json",
      "deviceName": "小爱音箱",
      "triggerKeywords": ["让小茹箩"],
      "feishuReplyEnabled": true,
      "allowFrom": ["default"]
    }
  }
}
```

---

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `false` | 是否启用小爱频道 |
| `miotConfigPath` | - | `.mi.json` 文件路径（使用环境变量登录时可选）|
| `deviceName` | - | 设备名称（与米家 APP 中一致）|
| `triggerKeywords` | `["让小茹箩"]` | 触发 nanobot 的关键词 |
| `feishuReplyEnabled` | `true` | 复杂内容是否转发飞书 |
| `simpleResponseLengthThreshold` | `100` | TTS 语音回复的字数阈值 |
| `allowFrom` | `[]` | 允许的用户 ID |
| `pollIntervalSeconds` | `2` | 语音输入轮询间隔（秒）|

## 使用方法

### 唤醒 nanobot

对小爱音响说：**"让小茹箩 + 你的问题"**

例如：
- "让小茹箩告诉我今天有什么任务"
- "让小茹箩查一下明天天气"
- "让小茹箩帮我记一下今天下午三点开会"

### 响应路由规则

nanobot 会根据回复内容自动选择输出方式：

| 条件 | 输出方式 |
|------|----------|
| 字数 < 100 | 小爱 TTS 语音播放 |
| 包含代码块 ``` ` ``` | 飞书卡片 |
| 包含表格 `|` | 飞书卡片 |
| 字数 > 200 | 飞书卡片 |
| 其他 | 小爱 TTS 语音播放 |

## 消息流

```
用户: "小爱同学，让小茹箩告诉我今天有什么任务"
    ↓
XiaomiChannel._poll_voice_input() [每2秒轮询]
    ↓
MiOTService.get_conversation_history() [获取对话]
    ↓
_is_nanobot_trigger("让小茹箩告诉我今天有什么任务") [触发词检查]
    ↓ (是触发词)
_remove_trigger_keyword() [移除"让小茹箩"]
    ↓
_handle_message("告诉我今天有什么任务") [发送到总线]
    ↓
AgentLoop处理...
    ↓
TTS回复 / 飞书卡片
```

## 技术原理

### 自动登录流程

```
1. MiOTService.__init__()
   ↓
2. 检查 .mi.json 是否存在
   ↓
3. 如果不存在或 Token 过期：
   ├─ 读取 XIAOMI_USER_ID, XIAOMI_PASSWORD 从环境变量
   ├─ 调用 XiaomiAuth.login() 获取新令牌
   └─ 保存到 .mi.json
```

### Token 刷新流程 (401 无感刷新)

```
1. API 请求返回 401
   ↓
2. 调用 MiOTService.refresh_token()
   ↓
3. 如果 passToken 刷新失败：
   ├─ 从环境变量读取密码
   ├─ 调用 XiaomiAuth.login() 重新登录
   ├─ 更新内存中的 serviceToken
   └─ 写回 .mi.json 持久化
   ↓
4. 重试请求
```

## 常见问题

### 1. 环境变量登录失败

- 确认 `.env` 文件在正确位置（项目根目录）
- 确认 `XIAOMI_USER_ID` 是数字 ID，不是手机号
- 首次登录可能需要安全验证，按终端提示操作

### 2. 设备不在线

- 确认小爱音响已连接网络
- 确认账号下有该设备
- 确认 `deviceName` 与米家 APP 中的设备名称完全一致

### 3. TTS 播放无声

- 检查小爱音响音量
- 确认设备在线

### 4. 语音输入无响应

- 检查是否正确配置了 `.mi.json` 路径或环境变量
- 确认 `deviceName` 正确
- 检查日志中是否有错误信息
- 确保触发词以正确方式说出（以"让小茹箩"开头）

## 相关文档

- [MiGPT 项目](https://github.com/idootop/migpt-next)
- [mi-service-lite](https://github.com/idootop/mi-service-lite)
- [nanobot README](../README.md)
