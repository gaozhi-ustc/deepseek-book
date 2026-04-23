# legacy/

本目录收纳历史脚本，功能已被主线代码覆盖，**不要修改、不要引用**。仅作为历史追溯保留。

主线替代：

| 旧脚本 | 当前等价 |
|--------|----------|
| `md2docx.py`, `md2docx_improved.py`, `md2docx_v2.py`, `md2docx_latex.py` | `md_core.py` + `md_formatter.py` + `cli.py convert` |

如需恢复某段历史逻辑，请复制一份到主线模块中再改，不要直接 import `legacy/*`。
