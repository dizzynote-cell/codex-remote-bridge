# 可选 DeepSeek Harness 接入

Codex 的主机执行和同步方式不变。独立的 DeepSeek Remote Bridge 仍运行在用户自己的 Windows 电脑；云端 `/dsh/` 在所有者登录通过后提供静态页面和服务器快照；实时操作继续转发到本机。

## 通道

Windows 的 DSH 桥使用独立的转发令牌，主动通过 HTTPS 连接 `/api/device/dsh-relay`，领取 HTTP 请求并回传结果。不开放家庭电脑入站端口，不上传 Harness 用户身份、模型密钥或语音供应商密钥。它不领取 Codex 的任务队列。

在云端桥自己的环境文件中配置 `DSH_RELAY_TOKEN`，值应为至少 32 字符的随机独立令牌，不能复用 `SYNC_TOKEN`；配置 `PUBLIC_BASE_URL` 为自己的 HTTPS 入口。令牌不会发送到浏览器。

在 DSH 桥自己的私有 `.env` 中配置：

```ini
DSH_BRIDGE_BASE_PATH=/dsh/
DSH_BRIDGE_RELAY_URL=https://bridge.example.com/api/device/dsh-relay
DSH_BRIDGE_RELAY_TOKEN_FILE=<private-token-file>
DSH_BRIDGE_SIBLING_URL=http://127.0.0.1:8765/
```

令牌文件只放在私有配置/状态目录，不能加入 Git。DSH 默认仍监听回环 8766；修改基址或启用通道后需要在无活动任务时重启自己的 DSH 桥。云端部署配套的 `app.py`、`browser_sessions.py`、`dsh_gateway.py`、`dsh_snapshots.py` 和网页资源，并把独立 DSH 仓库的 `web/` 内容复制到云端 `dsh-web/`；只在获授权的维护操作中重启自己的云端桥服务。

## 登录与隔离

- `/dsh/` 未登录时跳转现有 OAuth；其 API、静态文件、下载和音频都需要验证登录。
- `/api/providers` 也是经过认证的状态接口。令牌接口只允许独立转发令牌，不能用访客提交的 provider 头代替认证。
- 浏览器 Cookie 和 Authorization 不会转发到 Windows 的 DSH 服务；来源检查在入口与 DSH 服务两处保留。
- 只转发 `/dsh/` 范围中的 GET、HEAD、POST，拒绝路径逃逸；任务提交超时不自动重新执行。
- 主机离线时可查看已保存的 DSH 快照，实时操作明确报离线；不会因此停止、重启或改发另一侧任务。
- Codex 显示原有额度，DSH 显示自己账户的余额，不换算、不混用。

## 切换和草稿

点击左上角 LOGO 选择后端。同源入口会记住上次使用的后端，各后端按会话分别保存文字草稿与待发附件。文字使用浏览器本地存储，附件使用本地 IndexedDB，均不为保存草稿而上传服务器。浏览器禁止附件存储时，离开前提示需要重新选择。

这不会转移真实会话，也不会取消任一后端正在执行的任务。清除浏览器站点数据会清除这些本地草稿。

## 回退

先停用主机转发配置，然后把本桥服务恢复到部署前备份；在获授权时重启本桥服务。不要重置原有数据库或删除其他项目配置。云端代码和环境文件都应在部署前保存有权限保护的回退副本。

## 配套功能

[服务器快照](dsh-cloud-snapshots.md)采用与 Codex 相同的最近六轮和按需历史机制，两个后端使用独立数据库。公网入口共用[登录设备管理](browser-sessions.md)：临时设备固定 1 小时、个人设备固定 7 天，可撤销其他登录。入口位于额度／余额详情最下面，长面板可内部滚动。
