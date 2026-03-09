# 小爱音响接入指南

将小爱音响接入 nanobot，实现语音对话和智能响应。

## 功能特性

- **TTS 语音回复**：简单问题直接通过小爱音响语音播放
- **飞书复杂响应**：复杂内容（长文本、代码、表格）自动转发到飞书发送卡片

## 接入方式

### 方式一：使用 .mi.json 配置文件（推荐）

#### 步骤 1：获取鉴权文件

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

#### 步骤 2：测试连接

```bash
nanobot miot-devices -c /path/to/.mi.json -d "小爱音箱"
```

如果能看到设备在线，说明连接成功。

#### 步骤 3：配置 nanobot

在 `~/.nanobot/config.json` 中添加：

```json
{
  "channels": {
    "xiaomi": {
      "enabled": true,
      "miotConfigPath": "/path/to/.mi.json",
      "deviceName": "小爱音箱",
      "feishuReplyEnabled": true,
      "simpleResponseLengthThreshold": 100,
      "allowFrom": ["default"]
    }
  }
}
```

### 方式二：手动配置（待完善）

手动输入 userId、passToken 和 deviceName（暂不支持，需要 token 刷新机制）。

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `false` | 是否启用小爱频道 |
| `miotConfigPath` | - | `.mi.json` 文件路径（推荐使用）|
| `deviceName` | - | 设备名称（与米家 APP 中一致）|
| `feishuReplyEnabled` | `true` | 复杂内容是否转发飞书 |
| `simpleResponseLengthThreshold` | `100` | TTS 语音回复的字数阈值 |
| `allowFrom` | `[]` | 允许的用户 ID |
| `pollIntervalSeconds` | `2` | 语音输入轮询间隔 |

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

### 1. 找不到 .mi.json 文件

运行 `npx migpt-next account` 后，会在当前目录生成 `.mi.json` 文件。

### 2. 设备不在线

- 确认小爱音响已连接网络
- 确认账号下有该设备

### 3. TTS 播放无声

- 检查小爱音响音量
- 确认设备在线

### 4. 语音输入

当前版本支持 TTS 语音回复。语音输入功能开发中。

## 相关文档

- [MiGPT 项目](https://github.com/idootop/migpt-next)
- [mi-service-lite](https://github.com/idootop/mi-service-lite)
