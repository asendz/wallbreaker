import json

from wallbreaker.session import RunLog, normalize_inference_records


def test_runlog_aggregates_ordered_stream_and_metadata(tmp_path):
    log = RunLog(tmp_path)
    endpoint = type("Endpoint", (), {"name": "attacker", "protocol": "openai", "model": "m"})()
    log.inference_request("abc", endpoint, [{"role": "user", "content": "hello"}], system="sys", tools=[], operation="turn", parameters={"max_tokens": 3})
    log.inference_event("abc", {"type": "reasoning_delta", "text": "a"})
    log.inference_event("abc", {"type": "reasoning_delta", "text": "b"})
    log.inference_event("abc", {"type": "text_delta", "text": "c"})
    log.inference_event("abc", {"type": "text_delta", "text": "d"})
    log.inference_event("abc", {"type": "usage", "input_tokens": 1})
    log.inference_response("abc", status="ok", stop_reasons=["end"], duration_ms=12)

    rows = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == ["attack"]
    row = rows[0]
    assert row["action"] == "turn"
    assert row["stream"] == [
        {"channel": "reasoning", "text": "ab"},
        {"channel": "text", "text": "cd"},
    ]
    assert row["text"] == "cd"
    assert row["reasoning"] == "ab"
    assert row["stream_metadata"] == [{"type": "usage", "input_tokens": 1}]
    assert row["request"]["system"] == "sys"


def test_legacy_records_normalize_and_keep_source_lines():
    records = [
        {"kind": "run_meta"},
        {"kind": "inference_request", "inference_id": "x", "operation": "completion", "messages": [], "parameters": {}},
        {"kind": "inference_event", "inference_id": "x", "event": {"type": "text_delta", "text": "one"}},
        {"kind": "inference_event", "inference_id": "x", "event": {"type": "text_delta", "text": " two"}},
        {"kind": "inference_response", "inference_id": "x", "status": "ok"},
    ]
    compact = normalize_inference_records(records, [1, 4, 7, 9, 11])
    assert compact[0]["kind"] == "run_meta"
    assert compact[1]["kind"] == "scaffold"
    assert compact[1]["action"] == "complete"
    assert compact[1]["text"] == "one two"
    assert compact[1]["source_lines"] == [4, 7, 9, 11]


def test_response_fallback_does_not_duplicate_traced_stop_event(tmp_path):
    log = RunLog(tmp_path)
    endpoint = type("Endpoint", (), {"name": "demo", "protocol": "openai", "model": "m"})()
    stop = {"type": "stop", "stop_reason": "end_turn"}
    log.inference_request("abc", endpoint, [], system=None, tools=None, operation="turn", parameters={})
    log.inference_event("abc", stop)
    log.inference_response("abc", status="ok", stream_events=[stop])

    row = json.loads(log.path.read_text(encoding="utf-8"))
    assert row["stream_metadata"] == [stop]


def test_inference_kinds_follow_scaffold_roles(tmp_path):
    cases = [
        ("attacker", "completion", "attack", "complete"),
        ("target", "completion", "target", "complete"),
        ("judge", "completion", "judge", "complete"),
        ("anything", "agent_turn", "scaffold", "plan_and_route"),
        ("art", "image_generation", "art", "generate_image"),
    ]
    for index, (name, operation, expected_kind, expected_action) in enumerate(cases):
        log = RunLog(tmp_path / str(index))
        endpoint = type("Endpoint", (), {"name": name, "protocol": "openai", "model": "m"})()
        log.inference_request(
            str(index), endpoint, [], system=None, tools=None,
            operation=operation, parameters={},
        )
        log.inference_response(str(index), status="ok")
        row = json.loads(log.path.read_text(encoding="utf-8"))
        assert row["kind"] == expected_kind
        assert row["action"] == expected_action
