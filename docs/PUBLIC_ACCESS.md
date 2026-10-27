# 公网访客入口与 SSH 转发

日期：2026-10-27。

## 入口与范围

- 公网入口：https://rag.semi-overt.com/ ，首页跳转到当前交付应用的聊天页。
- 仅开放“动画作画交接RAG”（阿里云＋Exa交付应用）的访客聊天；34条来源卡、必要引用及现有联网策略保持不变。
- 控制台仍从本机 http://127.0.0.1:18080 访问。公网不开放登录后台、其他应用、Service API、原始资料下载或上传。
- 关闭这个应用未使用的文件上传入口，并隐藏工作流步骤；保留引用和多轮对话，不改问答节点、索引、模型配置和历史实验。
- 访客问答使用用户已有的阿里云、DeepSeek和Exa凭据，可能产生费用。本次没有新增每月预算硬限额。

## 转发结构

~~~text
访客 HTTPS
  → Cloudflare 代理 DNS
  → 云服务器 Nginx 独立 rag 虚拟主机
  → 服务器 127.0.0.1:18081
  → SSH 反向隧道（LLLL）
  → 本机 127.0.0.1:18080
  → 现有 Dify
~~~

没有把 Dify 数据库、知识卡、PDF、页图或密钥迁移到云服务器。Cloudflare代理会经手公网访问流量，不代表绕过已配置的远端模型与搜索服务。

Nginx源模板为 deploy/nginx.rag.conf.template；实际安装路径为服务器 /etc/nginx/conf.d/rag.conf。只新增此虚拟主机，不改已有博客站点配置。使用服务器已有的通配符Origin CA证书；域名保持Cloudflare代理模式和现有严格TLS设置，不要直接关闭代理。

模板只放行一个聊天路径及必要静态资源、Web API。签发访客passport的请求必须携带这个应用的X-App-Code；会话权限仍由Dify校验。站点入口码是公开页面标识，不是管理员或供应商密钥。

## 本机前端配置

私有Dify环境文件中：

~~~dotenv
APP_API_URL=
WEB_API_CORS_ALLOW_ORIGINS=http://127.0.0.1:18080,https://rag.semi-overt.com
~~~

当前1.18.0镜像入口脚本将空APP_API_URL拼成同源 /api：本机页面走本机，公网页面走公网。控制台地址、APP_WEB_URL与FILES_URL保留原本机值，避免把其他历史应用的本地访问强制带到公网。因此控制台生成的默认应用链接可能仍显示本机地址，对外请使用上面的独立域名。

## 隧道日常操作

在项目根目录使用PowerShell 7：

~~~powershell
pwsh -File scripts/public_tunnel.ps1 -Action Start
pwsh -File scripts/public_tunnel.ps1 -Action Status
pwsh -File scripts/public_tunnel.ps1 -Action Stop
~~~

Start启动隐藏的本机守护进程；SSH断开后5秒重连，仅绑定服务器回环端口。Status只报告守护进程存在，不等于端到端连通。日志在被Git忽略的 work/public-access/tunnel.log 与 tunnel.error.log。

本次没有添加Windows开机或登录启动任务。电脑重启或退出登录后，需要先恢复Docker/Dify，再手动Start；关机、休眠、Docker停止或网络中断时，公网问答可能不可用。这是转发，不是全天候云端迁移。

## 恢复与撤下

- 临时停止转发：执行Stop；它只停止本项目守护进程及其SSH子进程，不停止其他项目或删除数据。
- 恢复：确认本机Dify可用后执行Start。
- 完全撤下：经明确授权后移除此子域名的DNS记录及服务器rag虚拟主机，并执行Nginx配置检查与重载；不要改博客配置或全局清理Docker。
- 本机更改前的环境及应用配置保存在被Git忽略的 work/public-access/ 中，仅用于本次回退，不公开提交。

## 验收边界

已确认DNS、HTTPS、首页跳转、内置浏览器聊天页面，以及公网passport、站点配置和参数接口正常。

公网聊天接口的合成“未公开动画项目”输入命中现有隐私澄清分支：HTTP 200，SSE收到回答及结束事件，工作流succeeded、4步骤、0 token。这验证了转发和零外部调用分支，不是新的付费模型回答验收。

登录页、管理页面、console API、Service API、原始文件路径、其他聊天路径和错误应用码的passport请求均返回404。未对外开放管理账号或底层数据库端口。

付费模型生成、联网质量和历史实验分数与公网连通验收分开记录。本次不重新建库、不重跑题集，也不把公网发布称为新的效果评测。
