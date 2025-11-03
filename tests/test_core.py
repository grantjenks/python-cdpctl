import argparse
import asyncio

import pytest

pytest.importorskip("aiohttp")

import cdpctl

from cdpctl import core


def test_package_reexports_core_symbols():
    assert cdpctl.main is core.main
    assert cdpctl.main_async is core.main_async
    assert cdpctl.CdpClient is core.CdpClient
    assert cdpctl.HttpClient is core.HttpClient
    assert cdpctl.TargetInfo is core.TargetInfo
    assert cdpctl.BooleanOptionalAction is core.BooleanOptionalAction


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


def test_dunder_main_delegates_to_core(monkeypatch):
    from cdpctl import __main__ as cli_main

    captured = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 7

    monkeypatch.setattr(core, "main", fake_main)

    result = cli_main.main(["list-tabs"])

    assert result == 7
    assert captured["argv"] == ["list-tabs"]
