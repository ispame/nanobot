# 小爱音响接入指南

将小爱音响接入 nanobot，实现语音对话和智能响应。

## 功能特性

- **语音输入**：通过"让小茹箩"触发词唤醒 nanobot，其他语音由小爱正常处理
- **TTS 语音回复**：简单问题直接通过小爱音响语音播放
- **飞书复杂响应**：复杂内容（长文本、代码、表格）自动转发到飞书发送卡片

## 接入方式

### 步骤 1：获取鉴权文件

使用 migpt-next 工具获取 `.mi.json` 配置文件：

```bash
# 1. 克隆 migpt-next
git clone https://github.com/idootop/migpt-next.git
cd migpt-next

# 2. 安装依赖
npm install

# 3. 运行登录命令
npx migpt-next account
```

这会在当前目录生成 `.mi.json` 文件，包含完整的鉴权信息。

### 步骤 2：测试连接

```bash
nanobot miot-devices -c /path/to/.mi.json -d "小爱音箱"
```

如果能看到设备在线，说明连接成功。

### 步骤 3：配置 nanobot

在 `~/.nanobot/config.json` 中添加：

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "miotConfigPath": "/path/to/.mi.json",
      "deviceName": "小爱音箱",
      "triggerKeywords": ["让小茹箩"],
      "feishuReplyEnabled": true,
      "simpleResponseLengthThreshold": 100,
      "allowFrom": ["default"],
      "pollIntervalSeconds": 2
    }
  }
}
```

### 步骤 4：运行

```bash
nanobot gateway
```

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `false` | 是否启用小爱频道 |
| `miotConfigPath` | - | `.mi.json` 文件路径（必填）|
| `deviceName` | - | 设备名称（与米家 APP 中一致）|
| `triggerKeywords` | `["让小茹箩"]` | 触发 nanobot 的关键词（必须以关键词开头）|
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

## 常见问题

### 1. 找不到 .mi.json 文件

运行 `npx migpt-next account` 后，会在当前目录生成 `.mi.json` 文件。

### 2. 设备不在线

- 确认小爱音响已连接网络
- 确认账号下有该设备
- 确认 `deviceName` 与米家 APP 中的设备名称完全一致

### 3. TTS 播放无声

- 检查小爱音响音量
- 确认设备在线

### 4. 语音输入无响应

- 检查是否正确配置了 `.mi.json` 路径
- 确认 `deviceName` 正确
- 检查日志中是否有错误信息
- 确保触发词以正确方式说出（以"让小茹箩"开头）

## 相关文档

- [MiGPT 项目](https://github.com/idootop/migpt-next)
- [mi-service-lite](https://github.com/idootop/mi-service-lite)
