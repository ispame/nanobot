---
name: freeaskinternet
description: 使用 FreeAskInternet 进行网络搜索和信息整理。支持 Bing、百度、DuckDuckGo 等搜索引擎，结合 LLM 生成答案。
homepage: https://github.com/nashsu/FreeAskInternet
metadata: {"nanobot":{"emoji":"🔍","requires":{"docker":true,"ports":[3000,3030,18080]}}}
---

# FreeAskInternet 网络搜索

使用 FreeAskInternet 进行本地网络搜索，无需 API Key。

## 启动服务

```bash
cd ~/WorkTable/openclaw_coder/FreeAskInternet

# 使用 Bing 搜索 (默认)
SEARCH_ENGINE=bing docker compose up -d

# 或使用百度搜索
SEARCH_ENGINE=baidu docker compose up -d
```

## 服务地址

- Web UI: http://localhost:3000
- 旧版界面: http://localhost:3030

## API 端点

后端 API: http://localhost:18080

### 直接调用搜索

```bash
# 调用后端 API 进行搜索
curl -X POST http://localhost:18080/api/search/get_search_refs \
  -H "Content-Type: application/json" \
  -d '{"query": "Python 教程", "model": "gpt-3.5-turbo", "ask_type": "search"}'
```

## 使用场景

1. **网络搜索**：查询最新信息、新闻、教程
2. **信息整理**：让 LLM 根据搜索结果整理答案
3. **中文搜索**：推荐使用 Bing 或百度引擎

## 可用 LLM

- GPT-3.5 (免费)
- Kimi (免费)
- Qwen (免费)
- GLM-4 (免费)
- Ollama (自定义)

## 停止服务

```bash
cd ~/WorkTable/openclaw_coder/FreeAskInternet
docker compose down
```

## 故障排除

- 检查容器状态: `docker compose ps`
- 查看日志: `docker compose logs -f`
- 重启服务: `docker compose restart`
