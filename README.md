# PDF 中文补译与全书审校 Skill

对照英文 PDF 和未完成中文版，补齐漏译与节译，保留原版图形布局、图例、书签和链接，并对已有及新增译文一同审校。

A reusable agent skill for completing and reviewing Chinese PDF translations while preserving layout and navigation. The helper scripts do not translate or review meaning automatically.

## 功能

- 支持多卷英文原档、未完成中文版，以及从英文原档开始的新译项目。
- 对照原页恢复缺页与缺失图形，补回完整译文。
- 默认使用思源黑体和 `English（中文译名）` 术语格式。
- 同时审校已有译文和新增补译，记录文字、逐页视觉和结构检查的实际范围。
- 附带文本提取、审校分批、受控文字替换及图片位置、书签、链接、字体检查脚本。

脚本不能判断译文准确性。OCR、复杂公式和原页恢复按 skill 流程单独处理。

## 安装

支持 Skills CLI 的客户端：

```bash
npx skills add LunageZz/pdf-zh-localization-skill --skill pdf-zh-localization
```

也可下载仓库，将 `skills/pdf-zh-localization` 整个文件夹放到客户端支持的 skills 目录。以 Codex 项目级目录为例：

```bash
git clone https://github.com/LunageZz/pdf-zh-localization-skill.git
mkdir -p /your/project/.agents/skills
cp -R pdf-zh-localization-skill/skills/pdf-zh-localization /your/project/.agents/skills/
```

不同客户端的导入与启用方式不同。不支持安装时，可上传该 skill 文件夹的 ZIP，要求助手先读取 `SKILL.md`。

## 调用示例

> 使用 $pdf-zh-localization。英文原档是……，未完成中文版是……。请补齐漏译和节译，对已有译文和新增译文一同全文审校。使用思源黑体，保留原版图片、图例、布局、书签和链接，交付完整中文合订本及核对说明。

只提供英文原档也可以。当前用户要求优先于 skill 默认值。

## 流程

```mermaid
flowchart LR
    A[原档清单与页码映射] --> B[逐页完整性检查]
    B --> C[翻译与术语统一]
    C --> D[原文本区域写回]
    D --> E[全部译文对照审校]
    E --> F[视觉与结构检查]
    F --> G[最终 PDF 与核对说明]
```

## 文件

| 路径 | 内容 |
| --- | --- |
| [SKILL.md](skills/pdf-zh-localization/SKILL.md) | 完整代理执行流程 |
| [工具说明](skills/pdf-zh-localization/README.md) | 命令与配置方法 |
| [实施注意事项](skills/pdf-zh-localization/references/implementation-notes.md) | 字体、布局及故障处理 |
| `skills/pdf-zh-localization/templates/` | 项目、补丁与审校记录模板 |
| `skills/pdf-zh-localization/scripts/` | PDF 辅助脚本与合成回归测试 |
| [验证记录](skills/pdf-zh-localization/VALIDATION.md) | 已完成测试及其范围 |

## 验证

```bash
python -m pip install -r skills/pdf-zh-localization/scripts/requirements.txt PyYAML
python scripts/validate_skill.py
python skills/pdf-zh-localization/scripts/self_test.py \
  --font-regular /path/to/SourceHanSansSC-Regular.otf \
  --font-bold /path/to/SourceHanSansSC-Bold.otf
```

合成测试覆盖文字替换、旋转页、矢量边框、图片、链接、书签、原文件不变及溢出拒绝。CI 检查结构、模板格式、语法和命令入口，不下载字体，不进行语义审校。

## 数据与许可

本仓库只包含通用流程、代码和示例，不包含原始文档、译文成品、字体、凭据或账号文件。外部翻译服务须符合当前项目的授权范围。

原创内容采用 [MIT License](LICENSE)。依赖与字体保留各自许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。
