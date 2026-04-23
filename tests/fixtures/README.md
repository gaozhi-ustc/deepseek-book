# tests/fixtures/

测试用 fixture。

## 可自动再生

运行 `python3.14 tests/build_fixtures.py` 会重生成：

- `reviewed_tracked.docx` — 由 `minimal.md` → `minimal_edited.md` 的 diff
  生成的 Track Changes docx。

## 需手工制作

下面这些需要在 Word 里打开 `reviewed_tracked.docx` 另存，构造为：

- `reviewed_plain.docx` — 把 `reviewed_tracked.docx` 里所有修订点"接受"
  （Accept All），另存为此文件，模拟"不开 Track Changes 直接改"。
- `reviewed_comments.docx` — 在 `minimal.md` 导出的干净 docx 里
  （用 `python3.14 cli.py convert tests/fixtures/minimal.md -o minimal.docx`
  得到），针对"第一段"插入 2-3 条批注（既有明确修改指令，也有意见），另存为此文件。
- `reviewed_mixed.docx` — 在 `reviewed_tracked.docx` 基础上再补 1-2 条批注。

如果缺失这些手工 fixtures，相关测试会被 pytest.mark.skip 跳过
（见 `tests/test_roundtrip.py` 的 `pytest.skip` 逻辑）。
