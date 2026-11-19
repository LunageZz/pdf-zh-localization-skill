# PDF 中文补译与全书审校 Skill

本包将“英文原档 + 未完成中文版 → 保留原版布局的完整中文校订 PDF”的流程整理成标准 `SKILL.md`，配有可运行的辅助工具。它不包含本次文档、Drive ID、外发许可或字体文件。

## 复用

如果使用的客户端支持导入自定义 skill，可导入本 ZIP，或把 `pdf-zh-localization` 文件夹放到该客户端指定的 skills 目录。不同客户端的安装方式不同；生成这个包并不代表已在账号中安装或启用。

在支持按名称调用的环境，可使用：

> 使用 $pdf-zh-localization。英文原档是……，未完成中文版是……。请补齐漏译和节译，并对已有译文与新增译文一同全文审校。使用思源黑体，保留原版图片、图例、布局、书签和链接，交付完整合订本及核对说明。

不支持安装 skill 的环境，可以上传 ZIP 并要求代理先读取其中的 SKILL.md，再按其流程执行。仅运行脚本不会自动翻译或完成全文审校。

## 最小工具示例

在下面命令中把 `SKILL_DIR` 设置为解压后的实际路径。字体使用用户可合法使用的完整字体文件，本包不附带字体。

```bash
SKILL_DIR=/path/to/pdf-zh-localization
python -m pip install -r "$SKILL_DIR/scripts/requirements.txt"

python "$SKILL_DIR/scripts/pdf_localize.py" inspect \
  --pdf /project/source/en.pdf --out /project/work/en_inventory.json

python "$SKILL_DIR/scripts/pdf_localize.py" extract \
  --pdf /project/source/en.pdf --out /project/work/en_text.json

# 由代理完成页码映射、英文/中文语义匹配后，生成含 id/page/source/zh 的 units.json。
python "$SKILL_DIR/scripts/pdf_localize.py" batches \
  --units /project/review/units.json --out-dir /project/review/batches

# patches.json 必须由代理逐项审核；坐标是对应基线 PDF 的未旋转页坐标。
python "$SKILL_DIR/scripts/pdf_localize.py" apply \
  --pdf /project/work/complete_baseline.pdf \
  --manifest /project/review/patches.json \
  --font-regular /project/fonts/SourceHanSansSC-Regular.otf \
  --font-bold /project/fonts/SourceHanSansSC-Bold.otf \
  --out /project/deliverables/final_zh.pdf

python "$SKILL_DIR/scripts/pdf_localize.py" audit \
  --pdf /project/deliverables/final_zh.pdf \
  --reference /project/work/complete_baseline.pdf \
  --out /project/qa/structure_report.json

python "$SKILL_DIR/scripts/self_test.py" \
  --font-regular /project/fonts/SourceHanSansSC-Regular.otf \
  --font-bold /project/fonts/SourceHanSansSC-Bold.otf
```

`apply` 不负责恢复缺失页面、不做 OCR、不做自动翻译、不编辑复杂公式；这些由 SKILL.md 的相应阶段完成。它拒绝覆盖输入文件和已存在输出，且字体缺字或低于最小字号仍无法放入时会停止。

`audit` 检查几何与导航结构，会把差异写入 JSON 并以非零退出码返回；它不判断译文准确性。中文版页数与英文不同，应先建立显式页码映射，不能直接将不对应的两份 PDF 交给逐页结构比较。
