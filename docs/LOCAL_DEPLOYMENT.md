# 本地 Dify / BGE-M3 接入与运行

状态：**2026-10-26本地服务与回答链路已接通，用户已配置密钥，开发30次及final-v1的90次生成已完成。** 以下13卡索引和无LLM节点调用描述是初始接线记录；source-v2后来建立了独立实验索引，source-v3修订未接入。没有公网发布。现成环境日常启动用Up，无需重复初始化、下载或填写凭据；版本状态见[收尾交接](HANDOFF.md)，模型配置见第6节。

## 范围与固定配置

- Dify 1.18.0，使用官方tag对应的Docker Compose；代码检出在私有work/vendor/dify，不把整套上游项目复制到公开源码。
- Compose项目名固定为animation-kb，数据库、Redis、向量库及模型卷均与其他项目独立。
- Dify仅绑定 `127.0.0.1:18080`；Ollama仅绑定 `127.0.0.1:11435`。不公开插件调试端口，不占用其他项目的80/443/5432/6379。
- Embedding采用Ollama 0.40.11提供的 `bge-m3`，容器内地址 `http://ollama:11434`，宿主诊断地址 `http://127.0.0.1:11435`。本机不映射GPU设备，选择官方0.40.11-rocm发行镜像所包含的同一CPU后端，避免下载标准镜像中更大的CUDA包；不要求安装AMD驱动，也不宣称使用AMD GPU。
- 使用Dify自带的经典知识库，向量存储选择Qdrant，不另外开发RAG平台；未启用可选KnowledgeFS或多人协同服务。上游必需的其他组件保留原有隔离关系。
- 初始化脚本的回答模型草案默认 `langgenius/deepseek/deepseek` / `deepseek-flash`；初始化不预设API Key，也不执行聊天或付费验证。后续已授权的实际实验另有独立入口和记录。

## 1. 初始化与启动

在仓库根目录使用PowerShell 7：

```powershell
uv sync --locked
pwsh -File scripts/local_stack.ps1 -Action Init
pwsh -File scripts/local_stack.ps1 -Action PullImages
pwsh -File scripts/local_stack.ps1 -Action Up
pwsh -File scripts/local_stack.ps1 -Action Status
```

Init准备固定版本的上游文件，生成私有.env及随机内部密码；再次执行不会重置数据库、密码或现有源代码。Init的HttpPort/OllamaPort参数只在首次创建.env时生效。PullImages只下载当前项目实际启用的公开镜像，利用官方crane 0.22.1导入Docker，保留已下载镜像和层缓存。Up只操作animation-kb项目，明确使用本地镜像、不再临时访问registry；首次镜像下载不承诺固定耗时。

本机已有回环代理服务127.0.0.1:7890，但系统代理未启用、Docker Hub直连超时，因此实际可用的下载方法为：

```powershell
pwsh -File scripts/local_stack.ps1 -Action Init -ImagePrefix docker.io
pwsh -File scripts/local_stack.ps1 -Action PullImages -PullProxy http://127.0.0.1:7890
pwsh -File scripts/local_stack.ps1 -Action Up
```

代理仅作用于本次公开镜像下载命令，下载完成后进程环境恢复；不修改系统代理、Docker Desktop全局设置或其他项目。工具不会加载其他Docker账号凭据。下载得到的tar及层缓存在work/images、work/image-cache，属于实际镜像导入与复用数据，不是额外验收证明文件。

另有以下**仅本项目**的公共镜像代理选项；本机最初尝试过该路径，部分下载较慢，后切换为上面的官方仓库命令级代理下载：

```powershell
pwsh -File scripts/local_stack.ps1 -Action Init -ImagePrefix docker.m.daocloud.io
pwsh -File scripts/local_stack.ps1 -Action PullImages
pwsh -File scripts/local_stack.ps1 -Action Up
```

该地址代理公开容器镜像下载，不接收原书、页图、知识条目或模型API Key。实际下载路径是第三方公共镜像代理，不写成Docker Hub直连；也不声称已经独立比对过上游镜像摘要。恢复直连时用 `-Action Init -ImagePrefix docker.io`，其他私有配置保持不变。Compose拉取并发限制为2，避免大量镜像并发占满本机网络。

## 2. 准备BGE-M3并做本地向量化检查

本机已经从官方模型注册表下载并按原生Ollama格式预置权重，组件摘要核对属于模型注册表协议的完整性检查，不是额外验收证明。当前环境可跳过PullEmbedding，直接做后面的本地向量化检查；只有重建且缺少模型时才需要重新拉取。

```powershell
pwsh -File scripts/local_stack.ps1 -Action PullEmbedding
$body = @{model='bge-m3'; input=@('这是本地接线测试，不是原书内容。','これは接続確認用の短文です。')} | ConvertTo-Json -Depth 4
$result = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11435/api/embed' -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$result.embeddings.Count
$result.embeddings[0].Count
```

本次已实际返回两条非空的1024维向量；该步骤不调用回答模型。模型为bge-m3:latest，实际ID790764642607、F16，ollama ps显示100% CPU。首次pull从公开模型仓库下载权重，不是加载本项目原书。模型标签可能更新，实验时记录实际Ollama版本、模型标签/版本信息和日期，不混用不同向量配置。

## 3. 本地管理员与模型插件

```powershell
.\.venv\Scripts\python.exe -m scripts.dify_local init
.\.venv\Scripts\python.exe -m scripts.dify_local plugins
```

init只连接本机Dify。首次创建的管理员邮箱/密码保存在被忽略的 `work/local/admin.json`，不打印密码；已有初始化实例而缺少账号文件时会停止，不重置账户。请在本机查看该文件并使用里面的账号登录Dify。

plugins请求从官方Marketplace安装Ollama和DeepSeek模型供应商，不关闭上游插件签名验证。安装是异步过程，应在Dify插件页面确认成功后再进行下一步；网络或Python依赖下载失败时看插件安装任务与本项目日志，不把“已提交安装”当成“安装完成”。下载插件与配置付费API是不同操作，此步骤不提交DeepSeek凭据。

初始安装记录：Ollama 1.0.3、DeepSeek 0.0.26安装成功，当时DeepSeek目录中的deepseek-flash为no-configure。此后用户已填写凭据并完成真实生成；不要把该历史目录状态当成当前待配置项，也不要只凭目录active就代替真实调用验收。

## 4. 绑定Embedding并导入来源草案

```powershell
.\.venv\Scripts\python.exe -m scripts.dify_local embedding
.\.venv\Scripts\python.exe -m scripts.dify_local import --include-drafts
.\.venv\Scripts\python.exe -m scripts.dify_local status
```

embedding只配置本地 `http://ollama:11434` 的bge-m3，设置Text Embedding默认模型；不会设置LLM密钥。容器使用服务名，不使用宿主的127.0.0.1。SSRF代理仅额外放行ollama这个具体内部域名，不放行整个私有网段。

import只接受corpus内来源卡，复用既有导出校验；默认拒绝未人工校订条目。此处显式 `--include-drafts` 仅用于内部准备，导入文档保留needs_human_review及内部草案提示，不提升知识状态。绝不导入evaluation中的题面、参考答案或评分，也不上传整本PDF或页图。

每条卡片导入为text_model；不使用需要LLM生成问答对的qa_model。按H1边界、2000 token上限分块，避免空行分块把页码/待校订标记与正文拆开。选择本地BGE-M3、高质量向量索引、语义检索、top_k=4并关闭Rerank。导入后等status中各文档indexing_status为completed；submitted或indexing不是已完成。本次13条文档均completed，共13个活动块，每个块均保留来源ID、PDF页码和needs_human_review。

私有 `work/local/dify-state.json` 保存本项目知识库ID、限定到该知识库的API Key及导入文档ID，供后续步骤消费。重复执行会跳过同名文档，不覆盖内容；语料版本变化时需要另建批次/知识库，不能假定本脚本已实现远端同步或旧文档删除。

需要建立新语料批次时，显式使用新的--state路径，如work/local/dify-state-v2.json；不要把正式评测后冻结的旧知识库直接改写。

## 5. 创建可配置回答模型的Chatflow草案

```powershell
.\.venv\Scripts\python.exe -m scripts.dify_local app
```

草案为：提问 → 本地来源检索 → 用户配置的LLM → 回答与出处。默认DeepSeek Flash，但不填密钥、不发布、不执行回答。脚本输出本地编辑入口；再次执行不会覆盖已经配置过的应用草案。

首次创建时可替换模型引用：

```powershell
.\.venv\Scripts\python.exe -m scripts.dify_local app --chat-provider '你的Dify供应商ID' --chat-model '你的模型调用名'
```

这两个参数只改变新草案的模型引用，不能代替在Dify中配置供应商凭据。已存在的草案请在LLM节点中修改，避免脚本覆盖人工调整。

初始接线时已保存四个节点，知识检索节点单独运行返回succeeded和4条带出处/校订标记的结果，当时未执行LLM节点。后续的受控完整API链路和批次生成见[模型配置手册](MODEL_CONFIGURATION.md)与[最终实验结果](FINAL_RESULTS.md)，不将两种验收阶段混写。

## 6. 用户填写DeepSeek配置

1. 用本地管理员登录Dify，进入工作区设置的模型供应商页面。
2. 打开DeepSeek供应商，在API Key字段（api_key）填写**你自己的密钥**，不要发到聊天里。已核对官方插件提供可选的API Base URL字段（endpoint_url），官方根地址使用 `https://api.deepseek.com`；不重复拼接 `/v1`。
3. 选择调用名 `deepseek-flash`。如果实际插件不支持该名字，先检查插件版本或使用支持自定义模型的兼容供应商，不能静默换成deepseek-chat等其他模型。
4. 保存或验证凭据可能触发API请求。仅在你确认费用和资料传输范围后操作；我不会为完成接入而代填其他项目密钥。
5. 回到本应用Chatflow的LLM节点，确认供应商与模型，检查温度和输出预算。初始化Flash草案及早期连通测试使用temperature=0、max_tokens=1024、thinking=false；后来两批独立对照实验使用2048输出上限、关闭思考和节点重试，并读回验证。不要覆盖原用户应用来冒充实验配置，也不要把DeepSeek专用参数套到其他供应商。更换供应商或配置后的新验证需要对应授权。
6. 先用普通合成文本检查模型连通，再在允许原书整理片段外发后运行RAG。没有完成这一步时，不声称端到端回答可用。

更换供应商、模型或生成参数后，G0/G1/G2必须统一使用新配置重新形成可比批次；不能只替换表现不佳的一组。

## 7. 查看日志与停止

```powershell
pwsh -File scripts/local_stack.ps1 -Action Logs
pwsh -File scripts/local_stack.ps1 -Action Stop
```

Stop只停止本项目服务，不删除容器数据、模型卷或私有配置。保留.env及work/vendor/dify/docker/volumes，数据库内容与密钥需一起保留。不要使用全局prune、恢复出厂或删除其他项目数据来处理本项目问题。

## 本轮实际排错

- 生成随机Redis密码后，最初遗漏同步上游模板中的CELERY_BROKER_URL，导致首次导入在队列派发处返回500。已在初始化脚本和本机.env中同步两者，仅重载本项目服务，并通过Dify重试接口恢复该文档；最终13条均完成索引。
- Dify 1.18的草案同步接口拒绝旧的environment_variables空字段，已从请求体移除；真实草案已保存并读回确认。
- 首轮按空行分块造成检索正文缺少来源页码/校订标记，已改为完整知识卡边界并重建这13条内部草案索引；不是改写原始知识卡或声称人工校订完成。
- 初始接线时内置页面检查接口不可连接，独立浏览器只确认登录页可渲染；未做界面全流程验收。后续独立实验草案已有真实生成API链路证据，但不等于原用户应用或source-v3的浏览器验收。

## 配置与数据位置

| 位置 | 用途 | 是否公开提交 |
| --- | --- | --- |
| deploy/compose.local.yaml | 本项目部署覆盖配置，无凭据 | 可以 |
| scripts/local_stack.ps1 | 初始化、启动、状态、停止及模型下载 | 可以 |
| scripts/dify_local.py | 仅限loopback的本地Dify接入操作 | 可以 |
| work/vendor/dify/docker/.env | 内部密码、地址和镜像下载源 | 不可以 |
| work/local/admin.json | 本地管理员账号 | 不可以 |
| work/local/dify-state.json | 知识库/应用ID和限定范围的知识库API Key | 不可以 |
| Docker卷animation-kb_ollama_models | 本项目BGE-M3权重 | 不可以 |

OCR配置步骤继续见 [模型配置手册](MODEL_CONFIGURATION.md) 与 [OCR说明](OCR.md)。本地部署、向量化、检索连通、回答正确性和公网交付分别记录，不互相替代。
