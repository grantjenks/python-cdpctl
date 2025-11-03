#!/usr/bin/env python3
"""
cdpctl.py — Fast Python CLI for Chrome DevTools Protocol (CDP)

Requirements (Python 3.10+):
  pip install aiohttp

Run Chrome with a DevTools port, for example (macOS):
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 --user-data-dir=/tmp/cdpctl

Examples:
  python cdpctl.py list-tabs
  python cdpctl.py new-tab https://example.com
  python cdpctl.py get-dom <target_id>
  python cdpctl.py navigate <target_id> https://news.ycombinator.com --wait load
  python cdpctl.py screenshot <target_id> --full --out hn.png
  python cdpctl.py print-pdf <target_id> --out page.pdf
  python cdpctl.py console-log <target_id> --duration 15
  python cdpctl.py network-log <target_id> --duration 15
  python cdpctl.py eval <target_id> "document.title" --by-value

Subcommands:
  list-tabs, browser-info, new-tab, close-tab, activate-tab
  navigate [--wait none|dom|load|idle]
  get-dom, get-html, get-dom-snapshot
  eval [--by-value] [--await-promise]
  screenshot [--out FILE] [--full] [--format png|jpeg] [--quality N]
  print-pdf [--out FILE] [--landscape] [--scale FLOAT] [--backgrounds]
  console-log [--duration SECS]
  network-log [--duration SECS]
  list-cookies
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

__all__ = [
    "BooleanOptionalAction",
    "CdpClient",
    "HttpClient",
    "TargetInfo",
    "main",
    "main_async",
]


# ----------------------------- HTTP helpers -----------------------------
@dataclass
class TargetInfo:
    id: str
    title: str = ""
    url: str = ""
    kind: str = ""
    description: str = ""
    faviconUrl: str = ""
    webSocketDebuggerUrl: str = ""

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "TargetInfo":
        return TargetInfo(
            id=d.get("id") or d.get("targetId") or "",
            title=d.get("title", ""),
            url=d.get("url", ""),
            kind=d.get("type", ""),
            description=d.get("description", ""),
            faviconUrl=d.get("faviconUrl", ""),
            webSocketDebuggerUrl=d.get("webSocketDebuggerUrl", ""),
        )


class HttpClient:
    def __init__(self, host: str, port: int, session: aiohttp.ClientSession):
        self.base = f"http://{host}:{port}"
        self.session = session

    async def list_tabs(self) -> List[TargetInfo]:
        for path in ("/json/list", "/json"):
            async with self.session.get(self.base + path) as resp:
                if resp.status == 200:
                    arr = await resp.json()
                    if isinstance(arr, list) and arr:
                        return [TargetInfo.from_json(x) for x in arr]
        return []

    async def browser_version(self) -> Dict[str, Any]:
        async with self.session.get(self.base + "/json/version") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def new_tab(self, url: Optional[str]) -> TargetInfo:
        if url:
            path = f"/json/new?{quote(url, safe='')}"
        else:
            path = "/json/new"
        async with self.session.get(self.base + path) as resp:
            resp.raise_for_status()
            return TargetInfo.from_json(await resp.json())

    async def close_tab(self, target_id: str) -> Dict[str, Any]:
        async with self.session.get(self.base + f"/json/close/{target_id}") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def activate_tab(self, target_id: str) -> Dict[str, Any]:
        async with self.session.get(self.base + f"/json/activate/{target_id}") as resp:
            resp.raise_for_status()
            return await resp.json()

    async def resolve_ws_url(self, target_or_ws: str) -> str:
        if target_or_ws.startswith("ws://") or target_or_ws.startswith("wss://"):
            return target_or_ws
        tabs = await self.list_tabs()
        for t in tabs:
            if t.id == target_or_ws:
                if t.webSocketDebuggerUrl:
                    return t.webSocketDebuggerUrl
                break
        raise RuntimeError(f"No websocketDebuggerUrl for id: {target_or_ws}")


# ----------------------------- CDP client -------------------------------
class CdpClient:
    def __init__(self, ws: aiohttp.ClientWebSocketResponse):
        self.ws = ws
        self._id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_subs: List[asyncio.Queue] = []
        self._reader_task = asyncio.create_task(self._reader())

    @classmethod
    async def connect(cls, ws_url: str, session: aiohttp.ClientSession) -> "CdpClient":
        ws = await session.ws_connect(
            ws_url,
            heartbeat=20.0,
            autoping=True,
            receive_timeout=60.0,
        )
        return cls(ws)

    async def close(self):
        if not self.ws.closed:
            await self.ws.close()
        if not self._reader_task.done():
            self._reader_task.cancel()
            with contextlib.suppress(Exception):
                await self._reader_task

    async def _reader(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if "id" in data and data.get("id"):
                        fut = self._pending.pop(int(data["id"]), None)
                        if fut and not fut.done():
                            fut.set_result(data)
                    else:
                        # Broadcast events
                        for q in list(self._event_subs):
                            if not q.full():
                                await q.put(data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            # Wake all pending futures with an error
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("WebSocket reader error"))

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def send(self, method: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        msg_id = self._next_id()
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        fut = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        await self.ws.send_str(json.dumps(payload))
        resp = await fut
        if "error" in resp and resp["error"]:
            err = resp["error"]
            raise RuntimeError(f"CDP error {err.get('code')}: {err.get('message')}")
        return resp.get("result", {})

    def subscribe(self, maxsize: int = 2048) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._event_subs.append(q)
        return q


# ----------------------------- Wait helpers -----------------------------
async def wait_ready_state(cdp: CdpClient, want: str, timeout_s: float) -> None:
    async def poll():
        while True:
            r = await cdp.send(
                "Runtime.evaluate",
                {"expression": "document.readyState", "returnByValue": True},
            )
            state = r.get("result", {}).get("value", "")
            if want == "dom" and state in ("interactive", "complete"):
                return
            if want == "load" and state == "complete":
                return
            await asyncio.sleep(0.1)

    await asyncio.wait_for(poll(), timeout=timeout_s)


async def wait_network_idle(cdp: CdpClient, quiet_ms: int, timeout_s: float) -> None:
    await cdp.send("Network.enable", {})
    q = cdp.subscribe()
    inflight = 0
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    quiet_deadline = loop.time() + quiet_ms / 1000.0

    while True:
        now = loop.time()
        if now >= deadline:
            raise TimeoutError("Timed out waiting for network idle")
        if inflight <= 0 and now >= quiet_deadline:
            return
        try:
            evt = await asyncio.wait_for(q.get(), timeout=min(0.25, max(0.0, deadline - now)))
        except asyncio.TimeoutError:
            continue
        if not isinstance(evt, dict):
            continue
        m = evt.get("method", "")
        if m == "Network.requestWillBeSent":
            inflight += 1
            quiet_deadline = loop.time() + quiet_ms / 1000.0
        elif m in ("Network.loadingFinished", "Network.loadingFailed"):
            inflight = max(0, inflight - 1)
            quiet_deadline = loop.time() + quiet_ms / 1000.0


# ----------------------------- Command impls ----------------------------
async def cmd_list_tabs(http: HttpClient, pretty: bool):
    tabs = [t.__dict__ for t in await http.list_tabs()]
    print(json.dumps(tabs, indent=2 if pretty else None))


async def cmd_browser_info(http: HttpClient, pretty: bool):
    info = await http.browser_version()
    print(json.dumps(info, indent=2 if pretty else None))


async def cmd_new_tab(http: HttpClient, url: Optional[str], json_flag: bool, pretty: bool):
    tab = await http.new_tab(url)
    if json_flag:
        print(json.dumps(tab.__dict__, indent=2 if pretty else None))
    else:
        print(tab.id)


async def cmd_close_tab(http: HttpClient, target_id: str, pretty: bool):
    res = await http.close_tab(target_id)
    print(json.dumps(res, indent=2 if pretty else None))


async def cmd_activate_tab(http: HttpClient, target_id: str, pretty: bool):
    res = await http.activate_tab(target_id)
    print(json.dumps(res, indent=2 if pretty else None))


async def cmd_navigate(http: HttpClient, target: str, url: str, wait: str, timeout_s: float):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            # Enable useful domains
            await cdp.send("Page.enable", {})
            await cdp.send("Network.enable", {})
            await cdp.send("Runtime.enable", {})
            await cdp.send("Page.navigate", {"url": url})
            if wait == "dom":
                await wait_ready_state(cdp, "dom", timeout_s)
            elif wait == "load":
                await wait_ready_state(cdp, "load", timeout_s)
            elif wait == "idle":
                await wait_network_idle(cdp, 500, timeout_s)
        finally:
            await cdp.close()


async def cmd_get_dom(http: HttpClient, target: str):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            r = await cdp.send(
                "Runtime.evaluate",
                {
                    "expression": "document.documentElement ? document.documentElement.innerText : ''",
                    "returnByValue": True,
                },
            )
            s = r.get("result", {}).get("value", "")
            print(s)
        finally:
            await cdp.close()


async def cmd_get_html(http: HttpClient, target: str):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            r = await cdp.send(
                "Runtime.evaluate",
                {
                    "expression": "document.documentElement ? document.documentElement.outerHTML : ''",
                    "returnByValue": True,
                },
            )
            s = r.get("result", {}).get("value", "")
            print(s)
        finally:
            await cdp.close()


async def cmd_get_dom_snapshot(http: HttpClient, target: str, pretty: bool):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            await cdp.send("DOMSnapshot.enable", {})
            snap = await cdp.send("DOMSnapshot.captureSnapshot", {"computedStyles": []})
            print(json.dumps(snap, indent=2 if pretty else None))
        finally:
            await cdp.close()


async def cmd_eval(
    http: HttpClient,
    target: str,
    expr: str,
    by_value: bool,
    await_promise: bool,
    pretty: bool,
):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            res = await cdp.send(
                "Runtime.evaluate",
                {
                    "expression": expr,
                    "returnByValue": by_value,
                    "awaitPromise": await_promise,
                    "replMode": True,
                },
            )
            print(json.dumps(res, indent=2 if pretty else None))
        finally:
            await cdp.close()


async def cmd_screenshot(
    http: HttpClient,
    target: str,
    out: Optional[str],
    full: bool,
    fmt: str,
    quality: Optional[int],
):
    if fmt not in ("png", "jpeg"):
        raise SystemExit("--format must be png or jpeg")
    if quality is not None and fmt != "jpeg":
        raise SystemExit("--quality only applies to jpeg")

    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            await cdp.send("Page.enable", {})
            params: Dict[str, Any] = {"format": fmt, "fromSurface": True}
            if quality is not None:
                params["quality"] = max(1, min(100, int(quality)))
            if full:
                lm = await cdp.send("Page.getLayoutMetrics", {})
                content = lm.get("contentSize", {})
                w = float(content.get("width", 800))
                h = float(content.get("height", 600))
                params["clip"] = {
                    "x": 0.0,
                    "y": 0.0,
                    "width": w,
                    "height": h,
                    "scale": 1.0,
                }
            res = await cdp.send("Page.captureScreenshot", params)
            data_b64 = res.get("data")
            if not isinstance(data_b64, str):
                raise RuntimeError("captureScreenshot produced no data")
            raw = base64.b64decode(data_b64)
            if out:
                with open(out, "wb") as f:
                    f.write(raw)
                print(out)
            else:
                # write base64 to stdout
                sys.stdout.write(data_b64)
        finally:
            await cdp.close()


async def cmd_print_pdf(
    http: HttpClient,
    target: str,
    out: Optional[str],
    landscape: bool,
    scale: float,
    print_backgrounds: bool,
):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            params = {
                "landscape": bool(landscape),
                "printBackground": bool(print_backgrounds),
                "scale": float(scale),  # 0.1 – 2.0
            }
            res = await cdp.send("Page.printToPDF", params)
            data_b64 = res.get("data")
            if not isinstance(data_b64, str):
                raise RuntimeError("printToPDF produced no data")
            raw = base64.b64decode(data_b64)
            if out:
                with open(out, "wb") as f:
                    f.write(raw)
                print(out)
            else:
                sys.stdout.buffer.write(raw)
        finally:
            await cdp.close()


async def cmd_console_log(http: HttpClient, target: str, duration: float):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            await cdp.send("Runtime.enable", {})
            await cdp.send("Log.enable", {})
            q = cdp.subscribe()
            until = asyncio.get_event_loop().time() + duration
            while asyncio.get_event_loop().time() < until:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(evt, dict):
                    continue
                if evt.get("method") == "Runtime.consoleAPICalled":
                    ty = evt.get("params", {}).get("type", "")
                    args = evt.get("params", {}).get("args", [])
                    print(f"console.{ty}: {json.dumps(args, ensure_ascii=False)}")
                elif evt.get("method") == "Log.entryAdded":
                    print(f"log: {json.dumps(evt.get('params', {}), ensure_ascii=False)}")
        finally:
            await cdp.close()


async def cmd_network_log(http: HttpClient, target: str, duration: float):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            await cdp.send("Network.enable", {})
            q = cdp.subscribe()
            until = asyncio.get_event_loop().time() + duration
            while asyncio.get_event_loop().time() < until:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                if not isinstance(evt, dict):
                    continue
                m = evt.get("method")
                p = evt.get("params", {})
                if m == "Network.requestWillBeSent":
                    url = p.get("request", {}).get("url", "")
                    print(f"REQ {url}")
                elif m == "Network.responseReceived":
                    url = p.get("response", {}).get("url", "")
                    status = p.get("response", {}).get("status", 0)
                    print(f"RES {status} {url}")
        finally:
            await cdp.close()


async def cmd_list_cookies(http: HttpClient, target: str, pretty: bool):
    ws = await http.resolve_ws_url(target)
    async with aiohttp.ClientSession() as sess:
        cdp = await CdpClient.connect(ws, sess)
        try:
            await cdp.send("Network.enable", {})
            cookies = await cdp.send("Network.getAllCookies", {})
            print(json.dumps(cookies, indent=2 if pretty else None))
        finally:
            await cdp.close()


# ----------------------------- Argparse/entry ---------------------------
class BooleanOptionalAction(argparse.Action):
    """Python 3.10 backport of argparse.BooleanOptionalAction"""

    def __init__(self, option_strings, dest, default=None, **kwargs):
        _option_strings = []
        for opt in option_strings:
            _option_strings.append(opt)
            if opt.startswith("--"):
                _option_strings.append("--no-" + opt[2:])
        super().__init__(_option_strings, dest, nargs=0, default=default, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, not option_string.startswith("--no-"))


async def main_async(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(
        prog="cdpctl.py",
        description="Python CLI for Chrome DevTools Protocol",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9222)
    p.add_argument("--timeout", type=float, default=10.0, help="default command timeout (secs)")
    p.add_argument("--pretty", action=BooleanOptionalAction, default=True, help="pretty-print JSON")

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-tabs")
    sub.add_parser("browser-info")

    s = sub.add_parser("new-tab")
    s.add_argument("url", nargs="?")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("close-tab")
    s.add_argument("id")

    s = sub.add_parser("activate-tab")
    s.add_argument("id")

    s = sub.add_parser("navigate")
    s.add_argument("id")
    s.add_argument("url")
    s.add_argument("--wait", choices=["none", "dom", "load", "idle"], default="none")

    s = sub.add_parser("get-dom")
    s.add_argument("id")

    s = sub.add_parser("get-html")
    s.add_argument("id")

    s = sub.add_parser("get-dom-snapshot")
    s.add_argument("id")

    s = sub.add_parser("eval")
    s.add_argument("id")
    s.add_argument("expr")
    s.add_argument("--by-value", action="store_true")
    s.add_argument("--await-promise", action="store_true")

    s = sub.add_parser("screenshot")
    s.add_argument("id")
    s.add_argument("--out")
    s.add_argument("--full", action="store_true")
    s.add_argument("--format", choices=["png", "jpeg"], default="png")
    s.add_argument("--quality", type=int)

    s = sub.add_parser("print-pdf")
    s.add_argument("id")
    s.add_argument("--out")
    s.add_argument("--landscape", action="store_true")
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--backgrounds", action="store_true", help="print CSS backgrounds")

    s = sub.add_parser("console-log")
    s.add_argument("id")
    s.add_argument("--duration", type=float, default=10.0)

    s = sub.add_parser("network-log")
    s.add_argument("id")
    s.add_argument("--duration", type=float, default=10.0)

    s = sub.add_parser("list-cookies")
    s.add_argument("id")

    args = p.parse_args(argv)

    timeout = aiohttp.ClientTimeout(total=args.timeout + 5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        http = HttpClient(args.host, args.port, session)
        if args.cmd == "list-tabs":
            await cmd_list_tabs(http, args.pretty)
        elif args.cmd == "browser-info":
            await cmd_browser_info(http, args.pretty)
        elif args.cmd == "new-tab":
            await cmd_new_tab(http, getattr(args, "url", None), getattr(args, "json", False), args.pretty)
        elif args.cmd == "close-tab":
            await cmd_close_tab(http, args.id, args.pretty)
        elif args.cmd == "activate-tab":
            await cmd_activate_tab(http, args.id, args.pretty)
        elif args.cmd == "navigate":
            await cmd_navigate(http, args.id, args.url, args.wait, args.timeout)
        elif args.cmd == "get-dom":
            await cmd_get_dom(http, args.id)
        elif args.cmd == "get-html":
            await cmd_get_html(http, args.id)
        elif args.cmd == "get-dom-snapshot":
            await cmd_get_dom_snapshot(http, args.id, args.pretty)
        elif args.cmd == "eval":
            await cmd_eval(http, args.id, args.expr, args.by_value, args.await_promise, args.pretty)
        elif args.cmd == "screenshot":
            await cmd_screenshot(http, args.id, args.out, args.full, args.format, args.quality)
        elif args.cmd == "print-pdf":
            await cmd_print_pdf(http, args.id, args.out, args.landscape, args.scale, args.backgrounds)
        elif args.cmd == "console-log":
            await cmd_console_log(http, args.id, args.duration)
        elif args.cmd == "network-log":
            await cmd_network_log(http, args.id, args.duration)
        elif args.cmd == "list-cookies":
            await cmd_list_cookies(http, args.id, args.pretty)


def main(argv: Optional[List[str]] = None) -> int:
    asyncio.run(main_async(argv))
    return 0


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass
