# 拾影：香港 2 核 / 4GB 单实例部署

在专用目录放本包，与超梦目录、数据卷分别管理。一个 Python 服务、一个 SlimSAM CPU 子进程；分割限 1 线程，容器最多 1 核、2800MB。此限额用于隔离资源，不能保证最大尺寸图片不触发 OOM，需实际验收。无需 GPU。生图和识别仍调用配置的外部 API，并按上游计费。

包不含密钥和用户数据；模型文件在 deploy/hongkong/models/slimsam（只读）。默认 simulation 不会真实生图。启用 live 需实际配置原渠道和模型，不运行付费验收请求。

## 配置

复制 deploy/hongkong/.env.example 为同目录 .env，chmod 600。设随机唯一 SITE_PASSWORD，至少 16 字符。仅此一个共享私有空间，无注册与个人账户隔离；不能公开匿名使用。API key只写服务器 .env。

```sh
docker compose -f deploy/hongkong/compose.yaml config --quiet
docker compose -f deploy/hongkong/compose.yaml up -d --build
curl --fail http://127.0.0.1:18791/api/health
docker compose -f deploy/hongkong/compose.yaml ps
```

正式浏览器入口必须由主机 HTTPS 反向代理指向 127.0.0.1:18791，并转发 Host、X-Forwarded-Proto 和 X-Forwarded-For。HTTP登录因 secure cookie 不会工作。不可将此端口改为公网开放；FORWARDED_ALLOW_IPS=* 仅适用于这个可信本机代理入口。

推荐在独立构建环境构建并 docker save/load 成品，避免在2核4GB同机运行npm或PyTorch安装构建。实际启动使用`up -d --no-build`。Linux x86_64目标镜像需相同CPU架构。

## 数据与验收

SQLite、草稿、会话、上传和结果在独立 named volume shiying-hongkong_data。不得执行 down -v。现有Windows用户数据未随包迁移；如需迁移，应先停原服务后一致复制整个 DATA_DIR，再校对文件与记录。历史没有自动清理，监控磁盘容量。

验收：HTTPS登录；未登录/api/config返回401；上传真实测试图、CPU智能选区；重启后草稿与图片仍在；核对 docker stats 峰值。不要用生成按钮做免费测试，live模式生成会真实计费。2800MB不足时应调整容量，不自动关闭智能分割或改换模型。

备份前停止 editor，一起备份整个数据卷；只拷sqlite主文件可能丢WAL事务。更新保留同一卷和密码。停止编辑服务不应停止超梦。

## 首次Linux验证（2026-10-12）

香港2核4GB容器中，单张512尺寸测试图的CPU prepare返回200，耗时约11.8秒；select返回200且生成真实Mask。1800MB限额曾导致推理峰值OOM，已提高至2800MB；测试结束RSS约575MB，主机可用约2.4GB。此为一次低并发功能验证，不代表多人性能承诺或大图峰值保证。保留CPU分割，不调用付费生成。
