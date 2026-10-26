# 本地日文 OCR

本工具只识别已经准备好的私有页图，不读取开发题，不调用云 OCR 或回答模型，也不上传、建立索引或改写知识卡。识别结果保留为待人工复核材料，不自动成为 G1 实验结果或 G2 校订语料。

## 环境与运行

在仓库根目录使用 PowerShell 7：

```powershell
uv sync --locked --extra ocr
uv run --locked --extra ocr python -m scripts.run_ocr
```

OCR 是可选依赖；基础页图、导出和评测工具仍可只用 `uv sync --locked` 安装。PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 锁定在 OCR extra 中，传递依赖由 uv.lock 固定。

默认抽样第 151、165、166 页，输出到被 Git 忽略的 `work/ocr/sample-v1`。输入为 `work/pages/page_index.json` 中的来源页图，不能将 evaluation 目录作为输入。输出必须在 work 内，且必须选择未使用的新目录，避免覆盖原始识别结果。

```powershell
uv run --locked --extra ocr python -m scripts.run_ocr --pages 56-61,151-152,165-167,224 --output work/ocr/core-v1
```

首次运行需要从官方 BOS 地址下载公开模型权重，后续使用本地缓存；下载模型不等于离线断网安装。本工具没有上传原书的接口。选择 CPU、4 线程，关闭文档方向、去畸变与文本行方向模型。固定检测模型 PP-OCRv5_mobile_det 和识别模型 PP-OCRv5_server_rec，不跟随 SDK 默认模型升级；具体参数也写入输出索引。

本机从PyPI下载依赖较慢，实际安装曾将锁定依赖导出后用清华镜像安装，未更改全局源或uv.lock中的默认源。遇到同类下载问题可使用以下一次性命令，仍按锁定版本及哈希安装：

```powershell
uv export --quiet --locked --extra ocr --format requirements-txt --no-emit-project --output-file work/ocr-requirements.txt
uv --system-certs pip sync --python .venv/Scripts/python.exe --index-url https://pypi.tuna.tsinghua.edu.cn/simple --require-hashes work/ocr-requirements.txt
```

## 2026-10-25 实际运行

- 三页抽样：151、165、166，保存于 `work/ocr/sample-v1`。
- 剩余九页：56–61、152、167、224，保存于 `work/ocr/core-rest-v1`；复用同一模型缓存和有效参数，没有重跑已成功的三页。
- 两批共覆盖12个不同的目标页，版本均为 PaddleOCR 3.7.0 / PaddlePaddle 3.3.1 / PaddleX 3.7.2。JSON、原样TXT和逐页索引均已生成，全部待人工复核。
- AI已对照前三页的原图与TXT，实际错误见 [抽样记录](OCR_REVIEW.md)。其他九页只完成识别和文件结构检查，不声称逐字审读或识别质量合格。

## 保留哪些结果

- `page-NNNN.json`：引擎原始输出，保留识别行、框位置、置信度和引擎配置。
- `page-NNNN.txt`：严格按引擎 rec_texts 的顺序换行拼接，不改错字、不替换数字/汉字、不做跨栏重排。
- `ocr_index.json`：供后续校订消费的来源页号、输入页图、输出文件、版本、参数及待校订状态；每成功一页更新一次。异常中断时只代表已写入的页面，不代表请求的整批完成。

原始页图索引保持不变：其中 ocr_performed=false 描述的是当时的页图提取，不因独立 OCR 批次被改写。印刷页码若原索引未确认则仍为 null，不根据 PDF 页序自动补齐。

## 抽样检查与校订边界

先对照来源页图检查词头、数字1/汉字一、语境标签、两栏顺序、图注和正文的关联。置信度不是正确率；文本行数、字符数也不是问答效果。

发现错字或错序时，原始 JSON/TXT 不动，将原样、拟校订内容、来源位置和待确认原因另行记录。只有人类真实复核后，才能把相应知识条目改为 human_reviewed。AI 目读不替代人工复核；图片中的箭头、彩线与操作关系不能仅凭 OCR 文本恢复。

G1 后续只能使用该批真实原始 OCR 文本与基础分块，不能以既有中文知识卡代替。G2 要使用另存且可追溯的校订版本。开发题和参考答案仍不得进入任一组的检索语料。

## 必要测试

```powershell
uv run --locked python -m unittest discover -s tests -v
```

OCR 工具的测试使用合成结果，只验证原始字形/顺序保留、私有输入边界、页号选择、输出来源信息和拒绝覆盖；不下载模型，也不证明真实识别质量。真实运行与抽样观察应单独记在开发记录中。

## 接口依据

- [PaddleOCR 官方 OCR Python 接口](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md)
- [PaddleOCR 官方 FAQ：BOS 模型下载源](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/FAQ.en.md)
