# 模型配置约定与接入手册

更新日期：2026-10-27。状态：**OCR、本地Dify、历史BGE-M3与DeepSeek链路保留；独立交付草案的阿里云Embedding及Exa已完成6场景真实接入验收。用户已确认当前材料审核完成；公网交付尚未完成。** 当前材料与历史记录的区别见[审核完成记录](HUMAN_REVIEW_COMPLETION.md)。以下初始13卡/单次连通记录保留为历史，不代表当前全部实验范围。

## 1. 用户配置原则

- 回答模型是用户自行配置的选项，不把开发者账号、API Key或某个供应商凭据写入源码。
- 本地项目默认使用DeepSeek Flash系列，经Dify的模型供应商设置接入；用户可更换供应商、API地址和模型名称。此处“本地”指应用在本地运行并调用API，不表示在本机加载DeepSeek权重。
- 默认调用名为 `deepseek-flash`，API根地址为 `https://api.deepseek.com`；已安装插件提供API Key字段api_key和可选的API Base URL字段endpoint_url。密钥由用户在Dify填写，不在聊天、前端或源码里填写，不重复拼接/chat/completions等路径。
- 官方调用名和服务端版本可能变化。正式实验必须记录调用名、当时对应版本、参数与日期，不能把可变别名当成永久固定版本；同一轮G0/G1/G2不得切换模型或参数。
- 本文不授权模型付费调用、资料外发或公开发布。保存/测试供应商配置也可能触发API请求，需在用户授权后进行。

## 2. 配置项总表

| 组件 | 本项目选择/默认值 | 用户需要配置什么 | 接入状态 |
| --- | --- | --- | --- |
| OCR检测 | PP-OCRv5_mobile_det | Python环境、可选依赖、来源页图、输出目录；无需API Key | 已接入 |
| OCR识别 | PP-OCRv5_server_rec | 同上；CPU线程可通过命令行调整 | 已接入 |
| Embedding | BGE-M3，经Ollama 0.40.11 CPU运行 | 本机已配置；Dify中的模型ID为bge-m3，地址http://ollama:11434，无需API Key | 已接入，实测1024维 |
| 回答模型 | DeepSeek Flash系列，调用名deepseek-flash | 用户自己的API Key；可更换供应商、地址和模型 | 用户已配置，实际生成成功 |
| Dify应用 | Dify 1.18.0，经典知识库与Chatflow | 本机已绑定本地Embedding、来源知识库及默认LLM引用 | 临时副本完整API链路通过，原草案未发布 |

当前没有额外接入Rerank服务或自动API模型裁判；本次评分与独立上下文审阅由助手及获授权的代理完成，未新增项目模型密钥。审阅不等于评分。若以后增加模型服务，必须同步补充本手册。

开发实验另有三份未发布草案（G0/G1/G2），用户授权后统一temperature=0、max_tokens=2048、thinking=false、节点重试关闭；G0无知识库，G1为12页原始OCR，G2为13条已获用户复核确认的来源卡。三组各10份实际回答已成功生成，均正常结束，无截断或补跑；评分待填写。原应用和旧待校订索引保留不覆盖，实际用量见[PILOT_RESULTS.md](PILOT_RESULTS.md)，配置和授权范围见[PILOT_EXPERIMENT.md](PILOT_EXPERIMENT.md)。

后续final-v1批次使用另外三份独立草案：同样的2048输出预算与关闭思考/重试，G1为28页原始OCR、G2为source-v2的34卡，共90份实际回答及评分。详情见[FINAL_EXPERIMENT.md](FINAL_EXPERIMENT.md)与[FINAL_RESULTS.md](FINAL_RESULTS.md)。评分仍未完成，source-v3修订未导入，不能把旧已确认卡的标签推给全部新卡。

**已经搭好的本机环境无需重新安装或重复填写凭据。** 可用work/local/admin.json中的本地管理员登录 `http://127.0.0.1:18080`；重建或更换模型时按第4节配置。所有安装、启动、停止、重建和排错命令集中在 [本地部署手册](LOCAL_DEPLOYMENT.md)。账号文件和work/local/dify-state.json含私有凭据，不要公开。

本次实际安装的供应商插件为Ollama 1.0.3、DeepSeek 0.0.26；用户配置后deepseek-flash状态为active，并已实际生成。插件目录状态与实际调用结果分别验收，不能仅凭active宣称连通。

## 3. OCR：已可执行的配置步骤

1. 在仓库根目录使用PowerShell 7，运行 `uv sync --locked --extra ocr`。
2. 按 [资料准备](DATA_PREPARATION.md) 配置私有来源指针并准备页图。原书路径只放在被忽略的work目录中。
3. 固定检测与识别模型由 `scripts/run_ocr.py` 中的DETECTION_MODEL、RECOGNITION_MODEL指定；当前不要求用户修改它们。首次运行会下载公开权重，之后复用本地缓存，无需供应商账号。
4. 使用未用过的输出目录执行，例如：

```powershell
uv run --locked --extra ocr python -m scripts.run_ocr --pages 151,165-166 --cpu-threads 4 --output work/ocr/user-sample-v1
```

5. 成功时终端逐页报告结果，输出包含JSON、TXT和ocr_index.json。对照原图检查文字和阅读顺序；生成文件不等于识别质量通过。

现有四批原始OCR结果不要覆盖：sample-v1、core-rest-v1、expansion-v2-text、expansion-v2-forms，合计28页。完整模型、参数、下载问题与已发现错误见 [OCR说明](OCR.md)、[抽样记录](OCR_REVIEW.md)和[扩展记录](CORPUS_V2_AND_FINAL.md)。

## 4. 回答模型：用户自行配置

本机凭据已由用户填写。以下是重建或更换模型时的配置步骤；真实生成仍须在相应费用、资料传输授权范围内进行：

1. 在实际部署的Dify中进入工作区设置的模型供应商页面。
2. 使用已安装的DeepSeek供应商，确认其ID为langgenius/deepseek/deepseek。当前插件接口返回的中文标签有乱码，找不到中文名称时以英文名称、图标和上述ID定位；后台模型调用名正常。
3. 在API Key字段填写自己的密钥；API Base URL填写https://api.deepseek.com或保留插件官方默认。不要把模型API Key当成Dify应用API Key。
4. 在Studio打开“动画作画交接·本地草案”，选择LLM节点，模型使用deepseek-flash。初始配置和本次受控测试使用temperature=0、max_tokens=1024、thinking=false，后者对应“思考模式”关闭；不要把DeepSeek专用参数套用到其他供应商。本次服务接受这些参数，完整测试正常结束。测试前实际读到原草案max_tokens=393201、thinking=true、节点重试开启且最多3次，故另建临时副本限制输出、关闭思考/重试，未覆盖用户草案；这次通过不能代表原草案当前参数也已验收。
5. 获得调用授权后，用不包含原书或评测数据的普通文本做最小连通检查，再在资料外发范围确认后接入检索上下文。
6. 若配置提示401，检查密钥和账号授权；若提示模型不存在，检查调用名与供应商；若提示参数不支持，核对实际服务和插件参数。没有真实API调用时，不能宣称这些错误场景已逐一实测。

2026-10-26实测：合成文本连通后，用户另行授权发送检索片段并执行1次完整问答。临时副本的4个节点全部成功，返回4条带PDF页码与needs_human_review标记的来源记录；输入1311、输出431、合计1742 tokens，工作流耗时约7.33秒。临时应用已移除，实际回答及事件保存在被忽略的work/local/rag-smoke-2026-10-26.json。Dify费用字段返回0，不据此认定免费；实际扣费以供应商账单为准。本次授权不覆盖后续批量测试或公开发布。

更换回答模型时，先在模型供应商中添加自己的服务，再回到本应用LLM节点选择对应模型；不需要修改本项目源码。首次用脚本创建另一份草案时也可传入--chat-provider和--chat-model，已有草案不会被脚本覆盖。

更换回答模型后属于新的实验配置，不能与旧配置的部分结果拼成同一组对照。

## 5. BGE-M3：已配置值与重建步骤

2026-10-27补充：独立交付草案新增阿里云官方`text-embedding-v4` API配置和默认Exa分支，新Key均为空，旧BGE配置不变。新接口参数、地域、填写位置及激活命令见[交付配置手册](DELIVERY_CONFIGURATION.md)。官方系列别名不等同已确认的开源4B型号；远端建库需要发送来源卡，尚未执行。

本机已经部署并通过实际向量化和Dify索引检查：

1. 服务为Ollama 0.40.11，使用官方0.40.11-rocm镜像中包含的CPU后端，不映射GPU。已预置公开bge-m3:latest权重，实际模型ID790764642607、F16，运行时显示100% CPU；不是训练了新模型。
2. Dify供应商为langgenius/ollama/ollama，类型Text Embedding，模型名bge-m3，Base URL为http://ollama:11434；无需API Key。模型上下文长度字段设置8192，属于Dify侧声明配置，不代表本轮完成了8k长文容量验收。
3. 宿主诊断地址为http://127.0.0.1:11435，Dify容器不能把该地址当作自己内部的127.0.0.1；因此Dify使用上面的服务名地址。端口仅回环绑定，未向局域网或公网开放。
4. 当前环境不用重复下载。重建时按LOCAL_DEPLOYMENT.md执行Init、PullImages、Up，缺少权重时再执行PullEmbedding；安装官方Ollama插件后运行scripts.dify_local embedding，即可注册同一配置。
5. 已用中日文合成短句得到两条1024维向量，13条来源卡均完成本地索引。每卡按H1边界、2000 token上限分块，实际共13个活动块，来源、PDF页码和待校订标记均保留。更换Embedding后应重新建立相应索引，不能假定旧向量兼容。

模型权重下载与推理文本外发是两件事。优先本地向量化；若改用远端服务，先确认材料传输范围和费用。

## 6. 当前验收范围与交付

用户要求：**所有模型接入完成后，必须逐项告知其配置步骤，不仅报告“已接入”。**

已验证：服务启动与API健康、本地管理员认证、官方插件安装、本地Embedding、来源索引与标记保留、真实检索接口及知识检索节点；另有DeepSeek合成文本、临时副本完整API链路、30份开发回答及90份final-v1回答。已保存评分和来源/参考独立复核；这些均不替代正确性验收。

未验证：原用户应用当前配置的生成表现、浏览器界面完整问答流程、独立效果结论、source-v3接入及公网交付。初始接线时内置页面检查接口不可连接，独立浏览器只检查了登录页；认证、配置和完整链路主要通过本地API核查。不能把独立实验草案结果当作原用户应用或新版数据的界面全流程验收。

安装与日常运行详见 [本地部署手册](LOCAL_DEPLOYMENT.md)，OCR细节见 [OCR说明](OCR.md)。所有模型的用途、版本、默认参数、填写位置与检查方法已集中说明；以后新增模型或更改服务时应同步更新，而不是只报告“接入成功”。

交付时另列用户实际只需填写的项目；未完成的配置项明确标为待配置，不通过借用其他项目凭据来凑齐。模型连通、检索正确与最终答案正确分开验收。

## 官方依据

- [DeepSeek API首次调用与调用名](https://api-docs.deepseek.com/)
- [DeepSeek模型说明](https://api-docs.deepseek.com/quick_start/pricing)
- [Dify模型供应商配置](https://github.com/langgenius/dify-docs/blob/main/en/self-host/use-dify/workspace/model-providers.mdx)
