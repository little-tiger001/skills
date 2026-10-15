#!/usr/bin/env python3
"""Tiny HTTP server serving %TEMP%/cu_shot.bmp + a live HTML viewer.

The screenshot file is a BMP written by cu_ui.py's shot/watch commands:
cu_ui.py's shot/watch commands: %TEMP%/cu_shot.bmp (no PNG encoder needed -
pure ctypes BitBlt). Reads the file on every request so the latest frame shows.

Start it once alongside the bridge if you want a browser panel watching the
screen while the engine works. It is purely observational and not required for
any command.
"""
import http.server
import socketserver
import urllib.parse
import os
import sys
import tempfile

PORT = int(os.environ.get("CU_HTTP_PORT", "8899"))
SHOT = os.environ.get("CU_SHOT_PATH",
                      os.path.join(tempfile.gettempdir(), "cu_shot.bmp"))


INDEX_HTML = """<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>cu_ui 实时屏幕</title>
<style>
  body { margin: 0; background: #0e0e0e; color: #eaeaea;
         font: 13px/1.5 "Microsoft YaHei", "Segoe UI", sans-serif; }
  header { padding: 10px 16px; background: #1a1a1a; border-bottom: 1px solid #2a2a2a;
           display: flex; align-items: center; gap: 14px; }
  header .dot { width: 8px; height: 8px; border-radius: 50%;
                background: #2ecc71; box-shadow: 0 0 6px #2ecc71; }
  header .dot.stale { background: #e67e22; box-shadow: 0 0 6px #e67e22; }
  header .dot.dead { background: #c0392b; box-shadow: 0 0 6px #c0392b; }
  header .meta { color: #aaa; }
  header .meta b { color: #fff; }
  header a { color: #5dafe5; text-decoration: none; }
  .frame { text-align: center; padding: 8px; }
  .frame img { max-width: 100%; height: auto; display: block;
               border: 1px solid #2a2a2a; background: #000; }
  .ctrls { padding: 6px 16px; background: #1a1a1a; border-top: 1px solid #2a2a2a;
           display: flex; gap: 14px; align-items: center; font-size: 12px; color: #aaa; }
  .ctrls label { display: flex; align-items: center; gap: 4px; }
  .ctrls input[type=number] { width: 56px; background: #000; color: #fff;
                                border: 1px solid #444; padding: 2px 4px;
                                border-radius: 3px; }
  .ctrls input[type=checkbox] { accent-color: #5dafe5; }
</style>
</head>
<body>
<header>
  <span id="dot" class="dot"></span>
  <span class="meta">cu_ui live screen</span>
  <span class="meta">分辨率 <b id="res">—</b></span>
  <span class="meta">最后更新 <b id="age">—</b> 秒前</span>
  <span class="meta">FPS <b id="fps">0</b></span>
  <a href="/cu_shot.bmp" target="_blank">在新窗口打开</a>
</header>
<div class="frame">
  <img id="shot" alt="screenshot" src="/cu_shot.bmp?t=0">
</div>
<div class="ctrls">
  <label>刷新间隔 <input type="number" id="iv" value="400" min="100" max="5000" step="100"> ms</label>
  <label><input type="checkbox" id="on" checked> 自动刷新</label>
  <span class="meta" id="hint">提示：停止桥里的 watch 会让图不再变化（但页面仍继续轮询）</span>
</div>
<script>
const img = document.getElementById('shot');
const dot = document.getElementById('dot');
const res = document.getElementById('res');
const age = document.getElementById('age');
const fps = document.getElementById('fps');
const iv  = document.getElementById('iv');
const on  = document.getElementById('on');
let last = 0, frames = 0, fpsT = performance.now(), pending = null;

function poll() {
  if (!on.checked) { pending = setTimeout(poll, +iv.value); return; }
  const t = Date.now();
  img.onload = () => {
    last = Date.now(); frames++;
    if (img.naturalWidth) res.textContent = img.naturalWidth + '×' + img.naturalHeight;
  };
  img.onerror = () => { dot.className = 'dot dead'; };
  img.src = '/cu_shot.bmp?t=' + t;
  pending = setTimeout(poll, +iv.value);
}
setInterval(() => {
  if (last) age.textContent = ((Date.now() - last) / 1000).toFixed(1);
  const dt = (performance.now() - fpsT) / 1000;
  if (dt > 0) { fps.textContent = (frames / dt).toFixed(1); frames = 0; fpsT = performance.now(); }
  if (last && (Date.now() - last) > 3000) dot.className = 'dot stale';
  else if (last && (Date.now() - last) < 1500) dot.className = 'dot';
}, 500);
poll();
</script>
</body>
</html>
"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        pass  # quiet

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path in ("/cu_shot.bmp", "/shot.bmp"):
            try:
                with open(SHOT, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_error(404, "no shot yet - run `shot` or `watch` first")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/bmp")
            self.send_header("Cache-Control",
                             "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/health":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)


class T(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print("cu_ui live-screen on http://127.0.0.1:%d/  (shot: %s)" % (PORT, SHOT),
          flush=True)
    try:
        T(("127.0.0.1", PORT), H).serve_forever()
    except KeyboardInterrupt:
        pass
