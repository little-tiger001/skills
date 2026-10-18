#!/usr/bin/env python3
"""wps_agent.py — 用 WPS AI 助理身份密钥调用开放平台 v7 API。

仅使用 Python 标准库。密钥来源优先级：本 skill 目录的 .env > 进程环境变量 > 用户级环境变量。
脚本任何情况下都不回显完整密钥。

v7 接口的查询参数一律用 snake_case（如 page_size / page_token）。
部分接口只接受应用身份（app），用助理身份调用会返回
「this API does not support user authorization, required app scopes: [...]」。
"""
import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

TOKEN_URL = "https://account.wps.cn/api/authorization/agent/v1/token"
V7_BASE = "https://openapi.wps.cn"
FALLBACK_BASE = "https://api.wps.cn"
ENV_NAME = "AGENT_API_KEY"

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(SKILL_DIR, ".env")


def die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg):
    print(f"[WARN] {msg}", file=sys.stderr)


def info(msg):
    print(f"[INFO] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# 密钥与认证
# --------------------------------------------------------------------------
def load_api_key():
    """返回密钥字符串；找不到返回空串。"""
    key = ""
    if os.path.isfile(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip()
                if name.startswith("export "):
                    name = name[7:].strip()
                if name != ENV_NAME:
                    continue
                value = value.strip().strip('"').strip("'").strip()
                if value:
                    key = value
    if not key:
        key = os.environ.get(ENV_NAME, "")
    if not key:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
                key = winreg.QueryValueEx(handle, ENV_NAME)[0]
        except Exception:
            key = ""
    return key.strip()


def key_hint(key):
    return "未配置" if not key else f"已配置 (len={len(key)}, prefix={key[:5]!r})"


def require_key():
    key = load_api_key()
    if not key:
        die(
            "未检测到 AGENT_API_KEY。请把密钥写入本 skill 的 .env 文件：\n"
            f"  {ENV_FILE}\n"
            "形如 AGENT_API_KEY=apik:<sk_id>.<secret_key>（勿在对话中粘贴密钥）"
        )
    return key


def http(method, url, headers=None, body=None, timeout=60):
    """发一个请求，返回 (status, parsed_json_or_raw_dict)。不抛 HTTP 异常。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"_raw": raw[:500]}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        die(f"网络请求失败：{url} -> {exc.reason}")


def fetch_token(key):
    status, payload = http("POST", TOKEN_URL, body={"grant_type": "api_key", "api_key": key})
    if status != 200 or payload.get("result") != "ok":
        detail = payload.get("msg") or payload.get("message") or payload.get("_raw") or ""
        die(f"换取 AccessToken 失败 (HTTP {status})：{detail}")
    data = payload.get("data") or {}
    token = data.get("access_token")
    if not token:
        die("换取 AccessToken 失败：响应缺少 data.access_token")
    return token, int(data.get("expires_in") or 0)


def v7_get(path, params=None, token=None, allow_fallback=True):
    """GET 一个 v7 路径；openapi 网关 4xx 时回退 api.wps.cn。"""
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    bases = [V7_BASE] + ([FALLBACK_BASE] if allow_fallback else [])
    last_error = None
    for base in bases:
        status, payload = http(
            "GET", base + path + query, headers={"Authorization": f"Bearer {token}"}
        )
        if status >= 400:
            last_error = f"HTTP {status} via {base}: {str(payload)[:300]}"
            if base != FALLBACK_BASE:
                warn(f"{path} via {base} failed: HTTP {status}")
            continue
        if payload.get("code") not in (0, None):
            last_error = f"code={payload.get('code')} via {base}: {payload.get('msg')}"
            if base != FALLBACK_BASE:
                warn(f"{path} via {base} failed: {last_error}")
            continue
        if base != V7_BASE:
            info(f"content fallback to {base}（正常路径，不代表失败）")
        return payload
    die(f"请求失败：{last_error}")


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------
def items_of(payload):
    """从响应里取集合，兼容 items / Items 两种拼写。"""
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for name in ("items", "Items", "list", "records"):
            value = data.get(name)
            if isinstance(value, list):
                return value
    return None


def emit(payload, args, columns=()):
    if getattr(args, "format", "json") == "json" or not columns:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    rows = items_of(payload)
    if rows is None:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("（空）")
        return
    for row in rows:
        if not isinstance(row, dict):
            print(row)
            continue
        parts = []
        for label, key in columns:
            value = row
            for step in key.split("."):
                value = value.get(step) if isinstance(value, dict) else None
                if value is None:
                    break
            if isinstance(value, dict):
                value = value.get("datetime") or value.get("name") or json.dumps(value, ensure_ascii=False)
            parts.append(f"{label}={value}")
        print("  ".join(parts))


def page_args(args):
    params = {}
    if getattr(args, "page_size", None):
        params["page_size"] = args.page_size
    if getattr(args, "page_token", None):
        params["page_token"] = args.page_token
    return params


def authed():
    token, _ = fetch_token(require_key())
    return token


# --------------------------------------------------------------------------
# 链接 / 文档
# --------------------------------------------------------------------------
def extract_link_id(value):
    value = value.strip()
    value = value.split("?")[0].split("#")[0].rstrip("/")
    match = re.search(r"/l/([a-zA-Z0-9]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9]+", value):
        return value
    die(f"无法从链接中提取 link_id：{value}")


def resolve_file(link_id, token):
    payload = v7_get(f"/v7/links/{link_id}/meta", token=token)
    meta = payload.get("data") or {}
    drive_id = meta.get("drive_id")
    file_id = meta.get("file_id")
    if not drive_id or not file_id:
        die(f"链接元信息缺少 drive_id/file_id：{json.dumps(meta, ensure_ascii=False)[:300]}")
    return drive_id, file_id, meta


def cmd_token(args):
    key = require_key()
    info(f"密钥状态：{key_hint(key)}")
    token, expires_in = fetch_token(key)
    if args.print_token:
        print(token)
    else:
        print(json.dumps(
            {"result": "ok", "token_length": len(token), "expires_in": expires_in},
            ensure_ascii=False, indent=2,
        ))


def cmd_me(args):
    emit(v7_get("/v7/users/current", token=authed()), args)


def cmd_meta(args):
    token = authed()
    link_id = extract_link_id(args.link_id or args.url)
    info(f"link_id: {link_id}")
    drive_id, file_id, meta = resolve_file(link_id, token)
    print(json.dumps(
        {"link_id": link_id, "drive_id": drive_id, "file_id": file_id,
         "creator": (meta.get("creator") or {}).get("name", ""), "raw": meta},
        ensure_ascii=False, indent=2,
    ))


def cmd_read(args):
    token = authed()
    link_id = extract_link_id(args.link_id or args.url)
    info(f"link_id: {link_id}")
    drive_id, file_id, meta = resolve_file(link_id, token)
    info(f"drive_id={drive_id}, file_id={file_id}")

    payload = v7_get(
        f"/v7/drives/{drive_id}/files/{file_id}/content",
        params={"format": args.content_format},
        token=token,
    )
    data = payload.get("data") or {}
    content = data.get(args.content_format) or data.get("markdown") or data.get("plain") or ""
    file_name = (data.get("file_info") or {}).get("name", "") or f"doc_{link_id}"
    info(f"文件：{file_name}, 内容长度：{len(content)} chars")
    if not content:
        warn("正文长度为 0，请检查文档权限或格式。")

    if args.format == "json":
        out = json.dumps(
            {"file_name": file_name, "creator": (meta.get("creator") or {}).get("name", ""),
             "drive_id": drive_id, "file_id": file_id, "link_id": link_id,
             "src_format": data.get("src_format", ""), "content": content},
            ensure_ascii=False, indent=2,
        )
    elif args.format == "txt":
        out = content
    else:
        out = (
            f"---\n文件名：{file_name}\n"
            f"创建者：{(meta.get('creator') or {}).get('name', '')}\n"
            f"源格式：{data.get('src_format', '')}\n---\n\n{content}"
        )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(out)
        info(f"已保存到 {os.path.abspath(args.output)}")
    else:
        print(out)


# --------------------------------------------------------------------------
# 常用查询
# --------------------------------------------------------------------------
def cmd_calendars(args):
    emit(v7_get("/v7/calendars", token=authed()), args,
         columns=(("id", "id"), ("名称", "summary"), ("类型", "type"), ("角色", "role")))


def cmd_agenda(args):
    token = authed()
    calendar_id = args.calendar
    if not calendar_id:
        calendars = items_of(v7_get("/v7/calendars", token=token)) or []
        primary = next((c for c in calendars if c.get("type") == "primary"), None)
        calendar_id = (primary or (calendars[0] if calendars else {})).get("id") or "primary"
        info(f"未指定 --calendar，使用主日历 {calendar_id}")
    payload = v7_get(
        f"/v7/calendars/{calendar_id}/events", params=page_args(args), token=token
    )
    emit(payload, args,
         columns=(("id", "id"), ("标题", "summary"), ("开始", "start_time.datetime"),
                  ("结束", "end_time.datetime"), ("状态", "status")))


def cmd_chats(args):
    payload = v7_get("/v7/chats", params=page_args(args), token=authed())
    emit(payload, args, columns=(("id", "id"), ("名称", "name"), ("类型", "type"),
                                 ("状态", "status")))


def cmd_groups(args):
    payload = v7_get("/v7/groups", params=page_args(args), token=authed())
    emit(payload, args, columns=(("id", "id"), ("名称", "name"), ("类型", "type"),
                                 ("状态", "status")))


def cmd_mailboxes(args):
    payload = v7_get("/v7/mailboxes", params=page_args(args), token=authed())
    emit(payload, args, columns=(("id", "id"), ("名称", "name"), ("地址", "address")))


def cmd_drives(args):
    """盘列表。allotee_type 是必填，取 user / group / app。"""
    params = page_args(args)
    params["allotee_type"] = args.allotee_type
    payload = v7_get("/v7/drives", params=params, token=authed())
    emit(payload, args, columns=(("id", "id"), ("名称", "name"), ("归属类型", "allotee_type"),
                                 ("状态", "status")))


def cmd_ls(args):
    """列目录。parent_id 根目录传 0；可递归。"""
    token = authed()
    rows = []

    def walk(drive_id, parent_id, prefix, depth):
        params = {"page_size": args.page_size}
        page_token = ""
        while True:
            current = dict(params)
            if page_token:
                current["page_token"] = page_token
            payload = v7_get(
                f"/v7/drives/{drive_id}/files/{parent_id}/children",
                params=current, token=token,
            )
            data = payload.get("data") or {}
            for item in data.get("items") or []:
                item["_path"] = prefix + "/" + item.get("name", "")
                rows.append(item)
                if args.recursive and item.get("type") == "folder" and depth < args.max_depth:
                    walk(drive_id, item.get("id"), item["_path"], depth + 1)
            page_token = data.get("next_page_token") or ""
            if not page_token:
                break

    walk(args.drive, args.parent, "", 1)
    for row in rows:
        marker = "[D]" if row.get("type") == "folder" else "   "
        size = (row.get("size") or 0) / 1024
        row["_display"] = f"{marker} {size:>10.1f} KB  {row['_path']}"
    if getattr(args, "format", "json") == "text":
        for row in rows:
            print(row["_display"])
        print(f"\n合计 {len(rows)} 项", file=sys.stderr)
    else:
        print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_recycle(args):
    """回收站列表。"""
    payload = v7_get("/v7/deleted_files", params=page_args(args), token=authed())
    emit(payload, args, columns=(("id", "id"), ("名称", "name"), ("类型", "type"),
                                 ("大小", "size")))


def cmd_rm(args):
    """删除文件到回收站。默认 dry-run，必须显式 --yes 才真删。"""
    targets = [t.strip() for t in args.file.split(",") if t.strip()]
    if not targets:
        die("--file 为空")
    if not args.yes:
        print("DRY-RUN（未执行）。以下条目将被删除：", file=sys.stderr)
        for fid in targets:
            print(f"  POST /v7/drives/{args.drive}/files/{fid}/delete")
        print("确认无误后加 --yes 重跑。", file=sys.stderr)
        return
    token = authed()
    ok = 0
    for fid in targets:
        status, payload = http(
            "POST", f"{V7_BASE}/v7/drives/{args.drive}/files/{fid}/delete",
            headers={"Authorization": f"Bearer {token}"},
        )
        good = status == 200 and payload.get("code") in (0, None)
        ok += 1 if good else 0
        print(f"{'OK ' if good else 'FAIL'} {fid}  HTTP {status} "
              f"{payload.get('msg') or payload.get('message') or ''}")
    print(f"\n成功 {ok}/{len(targets)}；已删除的项目可在回收站恢复（recycle 命令）",
          file=sys.stderr)


def cmd_api(args):
    token = authed()
    path = args.path if args.path.startswith("/") else "/" + args.path
    if args.method.upper() == "GET":
        payload = v7_get(path, token=token, allow_fallback=args.fallback)
    else:
        body = json.loads(args.data) if args.data else None
        status, payload = http(
            args.method.upper(), V7_BASE + path,
            headers={"Authorization": f"Bearer {token}"}, body=body,
        )
        if status >= 400:
            die(f"HTTP {status}: {json.dumps(payload, ensure_ascii=False)[:400]}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------
def add_common(sub, name, help_text):
    parser = sub.add_parser(name, help=help_text)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser


def add_paging(parser):
    parser.add_argument("--page-size", type=int, default=20, help="每页条数，默认 20")
    parser.add_argument("--page-token", default="", help="翻页 token")


def main():
    parser = argparse.ArgumentParser(description="用 WPS AI 助理身份密钥调用开放平台 v7 API")
    sub = parser.add_subparsers(dest="command", required=True)

    p = add_common(sub, "token", "验证密钥并换取 AccessToken")
    p.add_argument("--print-token", action="store_true", help="打印 token 原文（默认只打印长度）")
    p.set_defaults(func=cmd_token)

    add_common(sub, "me", "当前用户信息").set_defaults(func=cmd_me)

    p = add_common(sub, "meta", "查询分享链接的元信息（drive_id/file_id）")
    p.add_argument("--link-id", help="link_id 或完整分享链接")
    p.add_argument("--url", help="完整分享链接")
    p.set_defaults(func=cmd_meta)

    p = sub.add_parser("read", help="读取分享文档正文")
    p.add_argument("--link-id", help="link_id 或完整分享链接")
    p.add_argument("--url", help="完整分享链接")
    p.add_argument("--format", choices=["md", "txt", "json"], default="md", help="输出格式")
    p.add_argument("--content-format", choices=["markdown", "plain"], default="markdown")
    p.add_argument("--output", help="写入文件；默认 stdout")
    p.set_defaults(func=cmd_read)

    add_common(sub, "calendars", "我的日历列表").set_defaults(func=cmd_calendars)

    p = add_common(sub, "agenda", "日程列表")
    p.add_argument("--calendar", help="日历 id，默认主日历")
    add_paging(p)
    p.set_defaults(func=cmd_agenda)

    p = add_common(sub, "chats", "会话列表")
    add_paging(p)
    p.set_defaults(func=cmd_chats)

    p = add_common(sub, "groups", "群组列表")
    add_paging(p)
    p.set_defaults(func=cmd_groups)

    p = add_common(sub, "mailboxes", "邮箱列表")
    add_paging(p)
    p.set_defaults(func=cmd_mailboxes)

    p = add_common(sub, "drives", "驱动盘列表（allotee_type 必填）")
    add_paging(p)
    p.add_argument("--allotee-type", choices=["user", "group", "app"], default="user",
                   help="归属类型：user=个人盘/我的云文档，group=团队盘/文档库，app=应用盘")
    p.set_defaults(func=cmd_drives)

    p = add_common(sub, "ls", "列出目录下的文件")
    p.add_argument("--drive", required=True, help="drive_id（先用 drives 命令拿）")
    p.add_argument("--parent", default="0", help="文件夹 id，根目录为 0")
    p.add_argument("--page-size", type=int, default=500)
    p.add_argument("--recursive", action="store_true", help="递归子目录")
    p.add_argument("--max-depth", type=int, default=3, help="--recursive 时的最大深度")
    p.set_defaults(func=cmd_ls)

    p = add_common(sub, "recycle", "回收站列表")
    add_paging(p)
    p.set_defaults(func=cmd_recycle)

    p = sub.add_parser("rm", help="删除文件到回收站（默认 dry-run，需 --yes）")
    p.add_argument("--drive", required=True, help="drive_id")
    p.add_argument("--file", required=True, help="file_id，多个用逗号分隔")
    p.add_argument("--yes", action="store_true", help="真正执行删除；不加则只打印")
    p.set_defaults(func=cmd_rm)

    p = add_common(sub, "api", "直接调用任意 v7 接口")
    p.add_argument("--method", default="GET")
    p.add_argument("--path", required=True, help="如 /v7/users/current")
    p.add_argument("--data", help="JSON 请求体（非 GET）")
    p.add_argument("--no-fallback", dest="fallback", action="store_false",
                   help="GET 时不回退 api.wps.cn")
    p.set_defaults(func=cmd_api, fallback=True)

    args = parser.parse_args()
    if args.command in ("meta", "read") and not (args.link_id or args.url):
        die("必须提供 --link-id 或 --url")
    # read 的 --format 是内容格式，其余命令是输出格式
    if args.command != "read" and not hasattr(args, "format"):
        args.format = "json"
    args.func(args)


if __name__ == "__main__":
    main()
