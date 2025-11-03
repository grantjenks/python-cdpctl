import argparse
import asyncio

import pytest

from cdpctl import core


def test_target_info_from_json_defaults():
    info = core.TargetInfo.from_json({"id": "abc123"})
    assert info.id == "abc123"
    assert info.title == ""
    assert info.webSocketDebuggerUrl == ""


def test_boolean_optional_action_toggles():
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature", action=core.BooleanOptionalAction, default=True)

    assert parser.parse_args([]).feature is True
    assert parser.parse_args(["--no-feature"]).feature is False
    assert parser.parse_args(["--feature"]).feature is True


async def _resolve_ws_url(client, monkeypatch):
    async def fake_list_tabs():
        return [
            core.TargetInfo(
                id="tab-1",
                webSocketDebuggerUrl="ws://example/test",
            )
        ]

    monkeypatch.setattr(client, "list_tabs", fake_list_tabs)

    assert await client.resolve_ws_url("ws://already/there") == "ws://already/there"
    assert await client.resolve_ws_url("tab-1") == "ws://example/test"

    with pytest.raises(RuntimeError):
        await client.resolve_ws_url("missing")


def test_http_client_resolve_ws_url(monkeypatch):
    client = core.HttpClient("localhost", 0, session=None)
    asyncio.run(_resolve_ws_url(client, monkeypatch))
