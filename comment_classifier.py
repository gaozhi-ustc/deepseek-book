"""comment_classifier.py — 用 Claude Sonnet 4.6 判断 Word 批注是
『明确修改指令』还是『意见/建议』。

设计约束：
  - 客户端依赖注入，方便测试 mock；client=None 直接降级为 opinion
  - 任何异常 / 解析失败 / schema 不全 都降级为 opinion（不抛出到调用方）
  - SYSTEM 用 prompt caching（ephemeral）摊低后续批注的成本
"""
import json


MODEL = 'claude-sonnet-4-6'
MAX_TOKENS = 500


SYSTEM_PROMPT = """\
你是中文技术书籍审校的辅助分类器。给定一条 Word 批注，判断它是"明确的文本修改指令"
还是"意见/建议"。

判别规则：
- edit：批注使用祈使/命令式或直接给出替换文本（"改成 X"、"X→Y"、"删掉"、
  "这句应为: ..."）
- opinion：批注在提问、讨论、建议但未给出确定的替换文本

边界判定：信息不足以确定替换文本时，返回 kind='opinion'。绝不自行发明替换文本。

输出必须是单个 JSON 对象，严格遵循：
{
  "kind": "edit" | "opinion",
  "new_text": string | null,
  "confidence": number,
  "reasoning": string
}
不要包装在 markdown code fence；不要有其他输出。
"""


USER_TEMPLATE = """\
批注锚点选中原文：
{anchor_text}

批注正文：
{comment_body}

锚点所在段落：
{block_text}

上下文：
{md_context}
"""


class ClassifierError(RuntimeError):
    """供外部显式捕获（实际上 classify 不抛出）。"""


def _degraded(reason: str) -> dict:
    return {
        'kind': 'opinion',
        'new_text': None,
        'confidence': 0.0,
        'reasoning': reason,
    }


def classify(*, client,
             block_text: str,
             anchor_text: str,
             comment_body: str,
             md_context: str) -> dict:
    """Classify a Word comment. 失败总是降级为 opinion。

    返回 dict：
      {'kind': 'edit' | 'opinion',
       'new_text': str | None,
       'confidence': float,
       'reasoning': str}
    """
    if client is None:
        return _degraded('degraded: no ANTHROPIC client provided')

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[{
                'type': 'text',
                'text': SYSTEM_PROMPT,
                'cache_control': {'type': 'ephemeral'},
            }],
            messages=[{
                'role': 'user',
                'content': USER_TEMPLATE.format(
                    anchor_text=anchor_text,
                    comment_body=comment_body,
                    block_text=block_text,
                    md_context=md_context,
                ),
            }],
        )
    except Exception as e:
        return _degraded(f'API error: {e}')

    # 取首个 text block
    try:
        text_raw = ''
        for blk in resp.content:
            blk_type = getattr(blk, 'type', 'text')
            if blk_type == 'text':
                text_raw += getattr(blk, 'text', '')
        text_raw = text_raw.strip()
    except Exception as e:
        return _degraded(f'unexpected response shape: {e}')

    try:
        data = json.loads(text_raw)
    except json.JSONDecodeError as e:
        return _degraded(f'could not parse JSON: {e}')

    # schema check
    required = {'kind', 'new_text', 'confidence', 'reasoning'}
    if not isinstance(data, dict) or not required.issubset(data.keys()):
        missing = sorted(required - set(data.keys() if isinstance(data, dict) else []))
        return _degraded(f'schema missing fields: {missing}')

    if data['kind'] not in ('edit', 'opinion'):
        return _degraded('schema: kind not in {edit, opinion}')

    try:
        conf = float(data['confidence'])
    except (TypeError, ValueError):
        return _degraded('schema: confidence not a number')

    return {
        'kind': data['kind'],
        'new_text': data['new_text'],
        'confidence': conf,
        'reasoning': str(data['reasoning']),
    }
