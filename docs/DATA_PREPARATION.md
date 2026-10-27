# 本地资料准备

本页的 prepare_pages / export_knowledge 工具只准备私有页图和来源条目，不调用模型、不上传、不建立检索索引。页图提取不等于 OCR；辅助目读也不等于校订。首批使用 pypdf/Pillow 提取该书的单图扫描页，不执行通用 PDF 页面渲染。独立OCR步骤见 [本地日文OCR](OCR.md)。

## 环境

在仓库根目录用 PowerShell 7：

```powershell
uv sync --locked
```

本地源配置为被忽略的 work/source.local.json，字段 local_path 指向用户提供的原 PDF，source_id 标识来源。其他机器需自行配置本机路径，不把私人路径写入公开源码。

## 准备目标页

```powershell
uv run --locked python scripts/prepare_pages.py
```

默认只处理 56–61、151–152、165–167 和 224 页。页图及 page_index.json 位于被忽略的 work/pages，供 OCR 和校订流程使用；索引记录原 PDF 页码与既有文本层。提取保留扫描图的原生像素，不放大制造细节；多图、旋转、裁剪或带文字层的页面会要求另行检查，不静默丢弃布局。书内页码需结合图像核对，不能由工具自动假定相同。

无文本层时text_file为null，不创建假OCR文字。独立PaddleOCR已处理12个目标页，结果另存在work/ocr，不回写页图索引；后续开发对照已运行，见[PILOT_RESULTS.md](PILOT_RESULTS.md)。新扩展页尚未OCR，范围评估见[OCR_EXPANSION.md](OCR_EXPANSION.md)，不能将目录/候选页查看当作新增识别结果。

## 来源知识条目

来源语料仅使用corpus/curated中的条目。评测问题、答案和评分不能导入知识库。当前12条保留此前用户复核确认；book-013的revision=2按原页修正，标为needs_human_review，不视为完成新一轮确认。默认导入仍保留复核门槛。

如需查看内部草案的导入格式：

```powershell
uv run --locked python scripts/export_knowledge.py --include-drafts
```

输出仅位于 work/dify-import，每条 Markdown 保留来源、页码、原词、语境和草案标签。该命令不访问 Dify。默认不带 --include-drafts 会拒绝未校订的条目，避免把开发材料静默当成已确认知识。

改变条目集合时使用新的 --output 子目录，不把不同语料版本的旧文件混入同一批导入。当前工具不执行删除或远端知识库同步。

路径入口分离只是防止误选评测文件，不能证明知识内容绝无泄漏；仍应保持资料整理与最终题集制作分离。目读条目可以辅助 G2 开发，但不得作为 G1 原始 OCR 结果或参考答案自动背书。
