# Markdown 转 DOCX 工具

将 Markdown 文件转换为符合《作者写作规范13条-1.27版》的 DOCX 文档。

## 安装依赖

```bash
pip install python-docx
```

## 使用方法

```bash
# 基本用法
python md2docx.py chapter3_new.md

# 指定输出文件
python md2docx.py chapter3_new.md -o 第3章.docx
```

## 功能特性

- ✅ 自动设置中文字体（宋体、黑体）
- ✅ 支持多级标题（1-4级）
- ✅ 支持表格转换（三线表格式）
- ✅ 支持代码块
- ✅ 支持 LaTeX 公式（文本格式）
- ✅ 自动编号图表
- ✅ 符合出版规范的段落格式

## 注意事项

1. 图片需要手动插入
2. LaTeX 公式以文本形式保留，需要在 Word 中使用公式编辑器转换
3. 代码注释需要手动翻译为中文
