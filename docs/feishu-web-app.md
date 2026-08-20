# 飞书网页应用配置

仅飞书模式不需要配置网页应用。启用网页模式后，将 `bridge.example.com` 替换为安装向导中填写的 HTTPS 域名。

1. 在飞书开发者后台启用网页应用。
2. 桌面端主页和移动端主页填写 `https://bridge.example.com/`。
3. 重定向 URL 添加 `https://bridge.example.com/api/auth/oauth/callback`。
4. H5 可信域名添加 `https://bridge.example.com`。
5. 发布应用版本，再使用同一飞书账号验证登录。

建议服务器只保存文字历史；项目文件留在 Windows 主力电脑或用户配置的同步盘中。
