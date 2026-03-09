# 小爱音响集成进度

## 当前状态：✅ 已完成

### 功能实现
- [x] MiOT 服务创建 (`nanobot/services/miot.py`)
- [x] 支持从 `.mi.json` 加载鉴权配置
- [x] 设备状态查询
- [x] TTS 语音播放
- [x] CLI 命令 `nanobot miot-devices`

### 配置方式
1. 使用 migpt-next 获取 `.mi.json`:
   ```bash
   cd /path/to/migpt-next
   npx migpt-next account
   ```

2. 在 nanobot 中配置:
   ```bash
   nanobot miot-devices -c /path/to/.mi.json -d "小爱音箱"
   ```

### API 说明
- **MiNA API** (`api2.mina.mi.com`) - 用于设备状态和控制
- **MIoT API** (`api.io.mi.com`) - 用于设备属性操作

### 待优化
- [ ] Token 刷新机制
- [ ] 直接支持 userId + password 登录
- [ ] 语音输入功能

## 使用示例

```python
from nanobot.services.miot import MiOTService

service = MiOTService(config_path="/path/to/.mi.json")
await service.play_tts("你好，小爱同学")
```

## 相关文件
- `nanobot/services/miot.py` - MiOT 服务
- `nanobot/cli/commands.py` - CLI 命令
- `nanobot/channels/xiaomi.py` - Xiaomi 频道
- `nanobot/channels/xiaomi.md` - 文档
