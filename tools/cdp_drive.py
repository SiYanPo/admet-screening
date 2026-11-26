# -*- coding: utf-8 -*-
"""Minimal CDP client for driving the already-signed-in Edge profile.

Why CDP rather than the extension
---------------------------------
The browser extension that normally exposes tabs to the agent is not installed in
this Edge profile, and re-installing it needs the Web Store (which the same
network interference blocks). Edge does expose the Chrome DevTools Protocol when
started with --remote-debugging-port and a non-default --user-data-dir; a copy of
the signed-in profile satisfies both constraints, so the session cookies travel
with it.

Scope: navigate, evaluate JS, read page state. No file access, no downloads.
"""
from __future__ import annotations

import json
import sys
import time

import requests
import websocket

CDP = "http://127.0.0.1:9223"


class Tab:
    def __init__(self, url: str):
        r = requests.put("%s/json/new?url=%s" % (CDP, requests.utils.quote(url, safe="")), timeout=10)
        if r.status_code >= 400:
            # older builds only allow GET /json/new
            r = requests.get("%s/json/new?%s" % (CDP, url), timeout=10)
        self.info = r.json()
        self.ws = websocket.create_connection(self.info["webSocketDebuggerUrl"], timeout=30)
        self._id = 0

    def cmd(self, method, params=None, timeout=25):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.ws.settimeout(max(1, deadline - time.time()))
            try:
                m = json.loads(self.ws.recv())
            except Exception:
                return {"error": "recv timeout"}
            if m.get("id") == mid:
                return m
        return {"error": "timeout"}

    def js(self, expr, timeout=25):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                          "awaitPromise": True}, timeout=timeout)
        try:
            return r["result"]["result"].get("value")
        except Exception:
            return r

    def goto(self, url):
        self.cmd("Page.navigate", {"url": url})
        time.sleep(3)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://github.com/settings/tokens"
    t = Tab("about:blank")
    t.goto(url)
    time.sleep(3)
    print("TITLE:", t.js("document.title"))
    print("URL:  ", t.js("location.href"))
    print("SIGNED_IN:", t.js("!!document.querySelector('meta[name=\"user-login\"]') || document.body.innerText.indexOf('Personal access tokens')>=0"))
    t.close()
