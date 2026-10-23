import asyncio

import pytest

from wallbreaker.agent.messages import TextDelta
from wallbreaker.config import Endpoint
from wallbreaker.providers.base import ProviderError
from wallbreaker.providers.request_gate import (
    configure_request_gate,
    gated_request,
    gated_stream,
    provider_gate_key,
)


@pytest.fixture(autouse=True)
def reset_request_gate():
    configure_request_gate(3, 0)
    yield
    configure_request_gate(3, 250)


def _endpoint(name="one", *, base_url="https://api.example/v1", key="shared"):
    return Endpoint(name, "openai", base_url, "model", api_key=key)


def test_same_origin_and_credential_are_serialized():
    configure_request_gate(1, 0)
    active = 0
    peak = 0

    def factory(label):
        async def stream():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                yield TextDelta(label)
            finally:
                active -= 1

        return stream

    async def collect(endpoint, label):
        return [event async for event in gated_stream(endpoint, factory(label))]

    async def run():
        return await asyncio.gather(
            collect(_endpoint("a"), "a"),
            collect(_endpoint("b"), "b"),
        )

    results = asyncio.run(run())
    assert peak == 1
    assert [result[0].text for result in results] == ["a", "b"]


def test_configured_concurrency_allows_parallel_requests():
    configure_request_gate(2, 0)
    active = 0
    peak = 0

    def factory(label):
        async def stream():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(0.01)
                yield TextDelta(label)
            finally:
                active -= 1

        return stream

    async def collect(label):
        return [event async for event in gated_stream(_endpoint(label), factory(label))]

    async def run():
        return await asyncio.gather(collect("a"), collect("b"))

    asyncio.run(run())
    assert peak == 2


def test_request_delay_spaces_request_starts(monkeypatch):
    configure_request_gate(2, 75)
    clock = [100.0]
    starts = []

    monkeypatch.setattr("wallbreaker.providers.request_gate.time.monotonic", lambda: clock[0])

    async def advance(delay):
        clock[0] += delay

    monkeypatch.setattr("wallbreaker.providers.request_gate.asyncio.sleep", advance)

    async def request():
        starts.append(clock[0])
        return True

    async def run():
        await asyncio.gather(
            gated_request(_endpoint("a"), request),
            gated_request(_endpoint("b"), request),
        )

    asyncio.run(run())
    assert starts == [100.0, 100.075]


def test_resolved_credential_defines_gate_not_environment_variable_name(monkeypatch):
    monkeypatch.setenv("FIRST_KEY", "same-secret")
    monkeypatch.setenv("SECOND_KEY", "same-secret")
    first = Endpoint("a", "openai", "https://api.example/v1", "m", api_key_env="FIRST_KEY")
    second = Endpoint("b", "openai", "https://api.example/other", "m", api_key_env="SECOND_KEY")
    assert provider_gate_key(first) == provider_gate_key(second)
    assert "same-secret" not in provider_gate_key(first)


def test_concurrency_429_is_retried_before_stream_starts(monkeypatch):
    calls = 0

    async def no_wait(_delay):
        return None

    monkeypatch.setattr("wallbreaker.providers.request_gate.asyncio.sleep", no_wait)

    def factory():
        async def stream():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ProviderError(
                    'HTTP 429: {"error":{"message":"rate limit exceeded: '
                    'too many concurrent requests"}}'
                )
            yield TextDelta("complete")

        return stream()

    async def run():
        return [event async for event in gated_stream(_endpoint(), factory)]

    events = asyncio.run(run())
    assert calls == 3
    assert events[0].text == "complete"


def test_429_after_partial_output_is_not_replayed(monkeypatch):
    calls = 0

    def factory():
        async def stream():
            nonlocal calls
            calls += 1
            yield TextDelta("partial")
            raise ProviderError("HTTP 429: too many concurrent requests")

        return stream()

    async def run():
        with pytest.raises(ProviderError, match="429"):
            async for _event in gated_stream(_endpoint(), factory):
                pass

    asyncio.run(run())
    assert calls == 1


def test_quota_429_is_not_retried():
    calls = 0

    def factory():
        async def stream():
            nonlocal calls
            calls += 1
            raise ProviderError("HTTP 429: insufficient_quota")
            yield  # pragma: no cover - makes this an async generator

        return stream()

    async def run():
        with pytest.raises(ProviderError, match="insufficient_quota"):
            async for _event in gated_stream(_endpoint(), factory):
                pass

    asyncio.run(run())
    assert calls == 1


def test_non_streaming_requests_use_the_same_retry_policy(monkeypatch):
    calls = 0

    async def no_wait(_delay):
        return None

    monkeypatch.setattr("wallbreaker.providers.request_gate.asyncio.sleep", no_wait)

    async def request():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderError("HTTP 429: too many concurrent requests")
        return {"ok": True}

    assert asyncio.run(gated_request(_endpoint(), request)) == {"ok": True}
    assert calls == 2
