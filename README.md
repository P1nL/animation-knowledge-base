# 动画作画交接知识库

题 A：面向中文使用者，解释日式动画作画交接、返修指示中的易混术语、语境和检查职责。依据给定资料回答并保留日文原词、页码和适用范围。

已确定技术路线：**Dify（知识库与问答工作流）+ PaddleOCR（本地文字识别）+ BGE-M3（Embedding）+ 用户可配置的回答模型（本地默认DeepSeek Flash系列API）**。选型与实际部署状态分开记录，详见 [技术选型](docs/PRD.md#技术选型)。

## 当前状态

**当前材料（2026-10-27）：** 34条来源卡、30道修订题参考及DEV-08修订参考，正文与前版相同。材料展示不附加整理者身份、生成方式或审核类别标识，保留内容、出处及页码。版本与使用方式见[材料说明](docs/HUMAN_REVIEW_COMPLETION.md)。

独立“阿里云＋Exa交付草案”已完成34卡建库和激活，6场景真实运行完成。引用URL补全与证据不足措辞两项修复已实现并同步，70项离线测试及A04/A05真实Code节点回放通过，见[回答输出修复](docs/ANSWER_OUTPUT_FIX.md)。未新增模型生成，历史9/12分数不回改；不新增仅官网过滤。索引保留source-v3快照，当前展示不附加身份或审核标识。原应用及历史实验不覆盖，尚未公网发布。

**本阶段已收尾。** 版本选择、运行入口、私有材料位置、Git状态及未完成边界统一见[收尾与交接](docs/HANDOFF.md)。

**2026-10-26：source-v2的28页/34卡已接入独立实验索引，final-v1三组90份回答及评审完成。G0/G1/G2为48/50/60分（各满分60），单一非盲评，不是准确率或独立验收。FINAL-21中文题面歧义另报29题敏感性结果。旧实验和原用户应用未覆盖，未公网发布。**

此前独立上下文复核曾发现FINAL-19作者前提、FINAL-20任务范围及book-016概括问题，详见[历史复核记录](docs/INDEPENDENT_AI_REVIEW.md)。这些意见已修订并获本次确认；旧分数未重评，题集仍为development_only，不重新成为held-out。

修订内容最初保存为source-v3 / final-v1.2-review，现以**source-v4 / final-v1.3-human-reviewed**记录审核后的状态，28页/34卡/30题范围不扩大。30题修订集未重新运行；source-v3的6场景开发验收不等于运行该题集。旧数据和分数不变，见[修订历史](docs/REVIEW_REVISION_V1_2.md)。

- 选题：日式动画作画交接与返修指示的术语消歧。
- 已查看给定 PDF 的目录和若干目标页面，不声称完成全书审读。
- 当前DEV-08参考revision=2已获本次确认，其余9题保留此前确认。题面仍是开发集，不进入独立测试集。
- source-v2固定34条来源卡；其中book-013修订版及新增21卡记录原页核对，不冒充新的。book-013修订依据是原文絵/線差异，不是为提高旧实验分数回填答案。
- 本地CPU OCR已覆盖28页；原始输出保留，另存主题知识单元的校订。表格核对限可见字段与表单边界，不声称全文逐字精校或逐格恢复。
- 离线评测工具只汇总实际保存的回答与明确评分，报告覆盖率、评分分母和配对差值；不会自己生成正确率。
- 原 PDF 不复制进公开源码；本机来源位置仅记录在被 Git 忽略的 work/ 中。
- 本地Dify入口为http://127.0.0.1:18080，BGE-M3只在本地向量化；DeepSeek凭据由用户配置。本轮三组独立草案使用2048-token输出上限、关闭思考和节点重试，未覆盖原应用。
- 尚未创建GitHub远端或公网问答入口；开发实验30次和本轮最终实验90次分别获得费用/片段外发授权，仅发送题面及必要检索片段，没有上传整本书或页图。两批授权不扩展到额外补跑或发布。

## 为什么不直接做全书百科

给定书中包含容易误读的中1/中一、中なし等术语，以及演出检查、作监检查、动画检查的责任区分。优先验证这个窄场景，而不是先建设通用聊天平台。

不预设 RAG 必然胜出。先使用同一模型对照无检索与检索回答；如果开发预实验没有发现有意义的差距，应在冻结最终测试集前调整选题。

## 文档

- [审核完成与当前材料](docs/HUMAN_REVIEW_COMPLETION.md)
- [收尾与交接（从这里继续）](docs/HANDOFF.md)
- [PRD 与技术选型](docs/PRD.md)
- [所有模型的配置约定与接入手册](docs/MODEL_CONFIGURATION.md)
- [阿里云Embedding＋Exa交付草案配置](docs/DELIVERY_CONFIGURATION.md)
- [默认联网触发与资料传输策略](docs/WEB_AUGMENTATION_POLICY.md)
- [本地Dify/BGE-M3部署与运行](docs/LOCAL_DEPLOYMENT.md)
- [实施顺序](docs/IMPLEMENTATION.md)
- [数据与问答评估协议](docs/EVALUATION.md)
- [开发记录](docs/DEVELOPMENT_LOG.md)
- [开发预实验题草案](evaluation/pilot.json)
- [三组开发预实验准备与调用范围](docs/PILOT_EXPERIMENT.md)
- [开发预实验实际生成与用量](docs/PILOT_RESULTS.md)
- [开发预实验评分、参考纠错与失败分析](docs/PILOT_AI_REVIEW.md)
- [资料查看与待校订事项](docs/SOURCE_REVIEW.md)
- [本地页图与导入文件准备](docs/DATA_PREPARATION.md)
- [本地日文 OCR](docs/OCR.md)
- [OCR扩展范围评估与修订边界](docs/OCR_EXPANSION.md)
- [28页资料扩展结果与30题冻结说明](docs/CORPUS_V2_AND_FINAL.md)
- [冻结的新测试题与参考](evaluation/final_v1.json)（已完成一轮生成；冻结元数据不改，不进入知识库）
- [最终三组实验运行约定](docs/FINAL_EXPERIMENT.md)
- [90份回答用量、评分与分析](docs/FINAL_RESULTS.md)
- [30题逐题评分理由](docs/FINAL_AI_REVIEW.md)
- [原页复查、题面消歧与独立复核交接](docs/REVIEW_FOLLOWUP.md)
- [独立上下文复核结果与待修订项](docs/INDEPENDENT_AI_REVIEW.md)
- [source-v3与final-v1.2-review修订说明](docs/REVIEW_REVISION_V1_2.md)
- [OCR 抽样问题与校订入口](docs/OCR_REVIEW.md)
- [离线评测工具](docs/EVALUATION_TOOL.md)
- [协作约定](AGENTS.md)

## 交付目标

公网可访问问答 URL，以及数据处理/选型/评估/失败分析/工具使用与个人工时的简要 Markdown。仅有本仓库不能代替题 A 要求的公网入口。

当前有独立阿里云＋Exa交付草案，旧应用及实验保留，尚无公网应用。引用/措辞修复已完成，新生成回答回归与公网交付仍待完成；不把历史G2的60/60写成系统准确率100%。此前开发实验41281 tokens、冻结测试146162 tokens及6场景验收21446 tokens分别记录，不合并为新效果分数。实际Git状态以仓库记录为准；私有运行资料不纳入提交，远端备份不等于公网应用交付。
