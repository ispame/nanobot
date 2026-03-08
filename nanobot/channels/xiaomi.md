# 小爱音响接入指南

将小爱音响接入 nanobot，实现语音对话和智能响应。

## 功能特性

- **语音输入**：通过小爱音响说话，nanobot 接收并处理
- **TTS 语音回复**：简单问题直接通过小爱音响语音播放
- **飞书复杂响应**：复杂内容（长文本、代码、表格）自动转发到飞书发送卡片

## 准备工作

### 1. 安装依赖

```bash
pip install python-miio
```

### 2. 获取设备 Token

小爱音响需要通过 IP 和 Token 进行连接。以下是获取 Token 的方法：

#### 方法一：miio-ndiscover 工具（推荐）

```bash
pip install miio
miio-ndiscover
```

这会扫描局域网内的小米设备，列出所有在线设备的 IP 和 Token。

#### 方法二：从米家 APP 导出

1. 打开 **米家 APP**
2. 点击右下角 **我的** → **设置** → **关于**
3. 连续点击顶部 banner 多次，进入 **开发者模式**
4. 返回设置页面，会出现 **导出设备共享密钥** 的选项
5. 导出的文件包含各设备的 Token

#### 方法三：Python 脚本

```python
from miio import Device

# 通过 IP 自动发现（需要设备在同一局域网）
device = Device.auto_discover("192.168.1.x")
print(device.token)
```

### 3. 确认设备 IP

确保小爱音响与运行 nanobot 的电脑在同一 WiFi 网络下，并记录设备的 IP 地址（可在路由器管理界面查看）。

## 配置

在 `~/.nanobot/config.json` 中添加：

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "ip": "192.168.1.100",
      "token": "your_32_char_token_here",
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
| `ip` | - | 小爱音响的 IP 地址 |
| `token` | - | 设备的 32 位 Token |
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
| 包含代码块 ```` ` ```` | 飞书卡片 |
| 包含表格 `\|` | 飞书卡片 |
| 字数 > 200 | 飞书卡片 |
| 其他 | 小爱 TTS 语音播放 |

## 常见问题

### 1. miio 连接失败

- 确认设备与电脑在同一 WiFi 网络
- 检查 IP 地址是否正确
- 尝试重新获取 Token

### 2. TTS 播放无声

- 部分设备可能不支持 `play_text` 方法
- 可以尝试使用其他 TTS 方式

### 3. 语音输入如何实现

当前版本实现了 TTS 语音回复功能。语音输入功能需要：
- 通过小爱同学的"语音备忘"或"自定义指令"触发
- nanobot 轮询获取最新录音
- 使用 Groq Whisper API 转写为文字

如需实现完整的语音输入功能，可以联系开发者获取支持。

## 相关文档

- [miio 官方文档](https://miio.readthedocs.io/)
- [Groq Whisper API](https://console.groq.com/docs/asr)
