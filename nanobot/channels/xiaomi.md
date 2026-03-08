# 小爱音响接入指南

将小爱音响接入 nanobot，实现语音对话和智能响应。

## 功能特性

- **语音输入**：通过小爱音响说话，nanobot 接收并处理
- **TTS 语音回复**：简单问题直接通过小爱音响语音播放
- **飞书复杂响应**：复杂内容（长文本、代码、表格）自动转发到飞书发送卡片

## 准备工作

### 1. 获取鉴权信息

小爱音响使用小米账号 (userId) + 密码/passToken + 设备名称 (did) 进行鉴权。

#### 获取 userId

1. 打开 **米家 APP**
2. 点击右下角 **我的** -> **设置** -> **关于**
3. 连续点击顶部 banner 多次，进入 **开发者模式**
4. 返回设置页面，会出现 **导出设备共享密钥** 的选项
5. 导出的文件中包含 `userId` 信息

或者使用 MiGPT 工具获取：

```bash
npx migpt-next account
```

#### 获取 passToken

passToken 可以是小米账号的密码，也可以是登录后获取的 passToken。

使用 MiGPT 工具获取（推荐）：

```bash
npx migpt-next account
```

这会输出类似以下信息：

```
✅ 登录成功
User ID: 1234567890
Pass Token: xxxxxx
```

#### 获取 deviceName (did)

1. 在 **米家 APP** 中找到你的小爱音响
2. 点击进入设备详情，记录设备名称（注意：必须是完全匹配的名称）
3. 或者使用 MiGPT 工具：

```bash
npx migpt-next list
```

## 配置

在 `~/.nanobot/config.json` 中添加：

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "userId": "your_user_id",
      "passToken": "your_pass_token",
      "deviceName": "你的小爱音响名称",
      "feishuReplyEnabled": true,
      "simpleResponseLengthThreshold": 100,
      "allowFrom": ["default"]
    },
    "feishu": {
      "enabled": true,
      "appId": "your_app_id",
      "appSecret": "your_app_secret",
      "allowFrom": ["*"]
    }
  },
  "providers": {
    "groq": {
      "apiKey": "your_groq_api_key"
    }
  }
}
```

### 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `false` | 是否启用小爱频道 |
| `userId` | - | 小米账号 userId |
| `passToken` | - | 小米账号密码或 passToken |
| `deviceName` | - | 设备名称（必须与米家 APP 中完全一致）|
| `feishuReplyEnabled` | `true` | 复杂内容是否转发飞书 |
| `simpleResponseLengthThreshold` | `100` | TTS 语音回复的字数阈值 |
| `allowFrom` | `[]` | 允许的用户 ID（当前填 `["default"]` 即可）|
| `pollIntervalSeconds` | `2` | 语音输入轮询间隔 |

### Groq API（可选）

配置 Groq API Key 后，可以实现语音转文字功能：

- 注册账号：https://console.groq.com
- 免费额度：每分钟 3 次请求，足以日常使用

## 运行

```bash
nanobot gateway
```

## 响应路由规则

nanobot 会根据回复内容自动选择输出方式：

| 条件 | 输出方式 |
|------|----------|
| 字数 < 100 | 小爱 TTS 语音播放 |
| 包含代码块 ``` ` ``` | 飞书卡片 |
| 包含表格 `|` | 飞书卡片 |
| 字数 > 200 | 飞书卡片 |
| 其他 | 小爱 TTS 语音播放 |

## 常见问题

### 1. 登录失败

- 确认 userId 和 passToken 正确
- 如果使用密码登录失败，可能是账号需要验证码
- 建议使用 MiGPT 工具获取 passToken

### 2. 设备找不到

- 确认 deviceName 与米家 APP 中完全一致（包括空格）
- 确认账号下有该设备

### 3. TTS 播放无声

- 部分设备可能不支持 TTS 功能
- 可以尝试使用其他 TTS 方式

### 4. 语音输入如何实现

当前版本实现了 TTS 语音回复功能。语音输入功能需要：
- 通过小爱同学的"语音备忘"或"自定义指令"触发
- nanobot 轮询获取最新录音
- 使用 Groq Whisper API 转写为文字

如需实现完整的语音输入功能，可以联系开发者获取支持。

## 相关文档

- [MiGPT 项目](https://github.com/idootop/migpt-next)
- [Groq Whisper API](https://console.groq.com/docs/asr)
