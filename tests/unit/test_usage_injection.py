"""usage 注入规则单元测试（规格 §12 保守策略）。"""
from __future__ import annotations

from easymodelgate.proxy.relay import maybe_inject_usage


def test_injected_when_missing_and_stream_true():
    body = {"model": "m", "messages": [], "stream": True}
    out, injected = maybe_inject_usage(body)
    assert injected is True
    assert out["stream_options"] == {"include_usage": True}
    assert "stream_options" not in body          # 原 body 不被就地修改


def test_not_injected_when_not_streaming():
    body = {"model": "m", "messages": []}
    out, injected = maybe_inject_usage(body)
    assert injected is False and "stream_options" not in out


def test_existing_include_usage_false_respected():
    so = {"include_usage": False}
    body = {"stream": True, "stream_options": so}
    out, injected = maybe_inject_usage(body)
    assert injected is False
    assert out["stream_options"] is so           # 同一对象，未修改
    assert out["stream_options"]["include_usage"] is False


def test_existing_include_usage_true_respected():
    so = {"include_usage": True}
    body = {"stream": True, "stream_options": so}
    out, injected = maybe_inject_usage(body)
    assert injected is False and out["stream_options"] is so


def test_existing_options_without_include_key_untouched():
    so = {"other_field": 1}
    body = {"stream": True, "stream_options": so}
    out, injected = maybe_inject_usage(body)
    assert injected is False
    assert out["stream_options"] == {"other_field": 1}
