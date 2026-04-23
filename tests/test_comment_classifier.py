"""comment_classifier.py 的测试。Anthropic 客户端 100% mock。"""
import json
from unittest.mock import MagicMock

import pytest

from comment_classifier import classify, ClassifierError


class _FakeAnthropic:
    """模拟 client.messages.create(...) 的最小 shape。"""
    def __init__(self, response_text: str, should_raise: bool = False):
        self._text = response_text
        self._raise = should_raise
        self.messages = MagicMock()
        self.messages.create = MagicMock(side_effect=self._create)

    def _create(self, **kwargs):
        if self._raise:
            raise RuntimeError('API boom')
        m = MagicMock()
        # Anthropic SDK 的 Message.content[0].text
        m.content = [MagicMock(text=self._text, type='text')]
        return m


def _ctx():
    return dict(
        block_text='前者发生在预训练阶段。',
        anchor_text='发生在',
        comment_body='改成：出现于',
        md_context='上下文内容',
    )


# ── edit case ──────────────────────────────────────────────
def test_classify_edit_high_confidence():
    client = _FakeAnthropic(json.dumps({
        'kind': 'edit',
        'new_text': '前者出现于预训练阶段。',
        'confidence': 0.92,
        'reasoning': '祈使型明确指令',
    }))
    result = classify(client=client, **_ctx())
    assert result['kind'] == 'edit'
    assert result['new_text'] == '前者出现于预训练阶段。'
    assert result['confidence'] == 0.92


# ── opinion case ───────────────────────────────────────────
def test_classify_opinion():
    client = _FakeAnthropic(json.dumps({
        'kind': 'opinion',
        'new_text': None,
        'confidence': 0.8,
        'reasoning': '未给出替换文本',
    }))
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['new_text'] is None


# ── 降级路径 ──────────────────────────────────────────────
def test_classify_no_client_returns_opinion():
    r = classify(client=None, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'degraded' in r['reasoning']


def test_classify_api_exception_returns_opinion():
    client = _FakeAnthropic('', should_raise=True)
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'API error' in r['reasoning']


def test_classify_malformed_json_returns_opinion():
    client = _FakeAnthropic('not a json{')
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert r['confidence'] == 0.0
    assert 'parse' in r['reasoning'].lower()


def test_classify_schema_missing_fields_returns_opinion():
    client = _FakeAnthropic(json.dumps({'kind': 'edit'}))  # 缺 confidence/new_text
    r = classify(client=client, **_ctx())
    assert r['kind'] == 'opinion'
    assert 'schema' in r['reasoning'].lower()


def test_classify_kwarg_shape_invokes_cache_control():
    """验证调用 API 时带了 cache_control=ephemeral（用 MagicMock.call_args 检查）。"""
    client = _FakeAnthropic(json.dumps({
        'kind': 'opinion', 'new_text': None, 'confidence': 0.5, 'reasoning': '-',
    }))
    classify(client=client, **_ctx())
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs['model'] == 'claude-sonnet-4-6'
    sys_list = kwargs['system']
    assert isinstance(sys_list, list)
    assert sys_list[0]['cache_control'] == {'type': 'ephemeral'}
