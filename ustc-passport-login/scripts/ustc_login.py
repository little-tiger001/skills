#!/usr/bin/env python3
"""登录中国科大统一身份认证（id.ustc.edu.cn，锐捷 RG-SourceID）。

配置来自本 skill 目录下的 .env（见该文件内注释）。仅需 requests + 一个 AES 实现。

两种登录形态：
  * service 形态：USTC_SERVICE 直接是 CAS 注册的服务地址
      https://www.ustc.edu.cn/                       CAS 直连
      https://jw.ustc.edu.cn/ucas-sso/login          ITDR 网关
  * entry 形态：USTC_ENTRY 是应用的「统一身份认证登录」入口，脚本自行跟随
      https://id.ustc.edu.cn/tokenworks/credits/auth/login   OIDC + PKCE

先用 --whoami 验证，再拿 session 去访问目标页面。
账号仅限本人使用。
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import quote, unquote

import requests

CAS_BASE = "https://id.ustc.edu.cn/cas"
LOGIN_URL = f"{CAS_BASE}/login"
POST_URL = f"{CAS_BASE}/login"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

_FIELD_RE = {
    "croypto": re.compile(r'<p[^>]*id="login-croypto"[^>]*>(.*?)</p>', re.S),
    "execution": re.compile(r'<p[^>]*id="login-page-flowkey"[^>]*>(.*?)</p>', re.S),
    "riskSystemSwitch": re.compile(r'<p[^>]*id="riskSystemSwitch"[^>]*>(.*?)</p>', re.S),
    "siteId": re.compile(r'<p[^>]*id="siteId"[^>]*>(.*?)</p>', re.S),
    "targetSystem": re.compile(r'<p[^>]*id="targetSystem"[^>]*>(.*?)</p>', re.S),
    "login-error-msg": re.compile(r'<p[^>]*id="login-error-msg"[^>]*>(.*?)</p>', re.S),
    "login-error-code": re.compile(r'<p[^>]*id="login-error-code"[^>]*>(.*?)</p>', re.S),
}

_AUTO_REDIRECT_RES = (
    re.compile(r"""window\.location\.replace\(\s*["']([^"']+)["']\s*\)""", re.I),
    re.compile(
        r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]*?content=["'][^"']*?url=([^"']+)["']""",
        re.I,
    ),
)

ERROR_CODES = {
    "1030027": "用户名或密码错误",
    "1030028": "账号已锁定",
    "1030031": "用户名或密码错误",
    "1410040": "账号无效",
    "1410041": "账号无效",
    "1320007": "验证码错误",
}


# --------------------------------------------------------------------------- .env


def load_env(path: str) -> dict:
    """极简 .env 解析：KEY=value，支持引号、# 注释、export 前缀；不做变量展开。"""
    cfg: dict = {}
    if not os.path.exists(path):
        return cfg
    with open(path, encoding="utf-8-sig") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            cfg[key] = val
    return cfg


# --------------------------------------------------------------------------- 加解密


def _aes_ecb_pkcs7_encrypt_b64(key: bytes, plaintext: str) -> str:
    """AES-128-ECB + PKCS7，输出 base64。与站点 CryptoJS 输出逐字节一致。"""
    data = plaintext.encode("utf-8")
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    if len(key) not in (16, 24, 32):
        raise ValueError(f"croypto 解出的密钥长度异常: {len(key)}")
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        out = enc.update(data) + enc.finalize()
    except ImportError:
        from Crypto.Cipher import AES  # type: ignore

        out = AES.new(key, AES.MODE_ECB).encrypt(data)
    return base64.b64encode(out).decode("ascii")


def redact(url: Optional[str]) -> str:
    """票据是一次性凭据，打印前抹掉。"""
    if not url:
        return ""
    return re.sub(r"([?&]ticket=)[^&]+", r"\1<已隐藏>", url)


class LoginError(Exception):
    """登录被拒或页面结构与预期不符。"""


# --------------------------------------------------------------------------- 主体


class UstcLogin:
    def __init__(self, username: str, password: str, timeout: int = 20):
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.result: Optional[requests.Response] = None
        self.error: Optional[str] = None
        self.ticket: Optional[str] = None
        self.redirect_to: Optional[str] = None
        self.cas_service: Optional[str] = None

    # ---- 内部 ----

    def _parse_form(self, page: str) -> dict:
        fields = {}
        for name, pat in _FIELD_RE.items():
            m = pat.search(page)
            fields[name] = unquote(m.group(1).strip()) if m else ""
        if not fields["croypto"] or not fields["execution"]:
            raise LoginError("登录页没渲染出 croypto / login-page-flowkey，页面结构可能又变了")
        return fields

    def _submit(self, form: dict) -> requests.Response:
        key = base64.b64decode(form["croypto"])
        payload = {
            "username": self.username,
            "type": "UsernamePassword",
            "_eventId": "submit",
            "geolocation": "",
            "execution": form["execution"],
            "captcha_code": "",
            "croypto": form["croypto"],
            "password": _aes_ecb_pkcs7_encrypt_b64(key, str(self.password)),
            "captcha_payload": _aes_ecb_pkcs7_encrypt_b64(key, json.dumps({})),
        }
        if form["riskSystemSwitch"] == "USTC":
            # 风控/设备指纹字段，服务端不强制；照站点自身 SDK 失败时的做法提交 error
            payload["risk_payload"] = _aes_ecb_pkcs7_encrypt_b64(key, json.dumps({"error": True}))
            payload["targetSystem"] = form["targetSystem"]
            payload["siteId"] = form["siteId"]
            payload["riskEngine"] = "true"
        return self.session.post(
            POST_URL,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://id.ustc.edu.cn",
                "Referer": self.cas_service or LOGIN_URL,
            },
            timeout=self.timeout,
            allow_redirects=False,
        )

    @staticmethod
    def _failure_reason(resp: requests.Response) -> Optional[str]:
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("location", "")
            if "exception.message=" in loc:
                return unquote(loc.split("exception.message=")[-1])
            return None
        if resp.status_code == 401:
            for pid in ("login-error-msg", "login-error-code"):
                m = _FIELD_RE[pid].search(resp.text)
                if m and m.group(1).strip():
                    val = m.group(1).strip()
                    return ERROR_CODES.get(val, f"登录被拒（错误码 {val}）")
            return "用户名或密码错误"
        if resp.status_code >= 400:
            return f"HTTP {resp.status_code}"
        return None

    def _follow_client_redirects(self, resp: requests.Response, max_hops: int = 6) -> requests.Response:
        """有些中间页（如 OIDC 的 /doc/oidc/callback）不用 302，而是 JS / meta-refresh 跳转。

        meta-refresh 的 URL 含 HTML 实体（``&amp;``），必须取到引号闭合处再反转义；
        按字符集截断会切掉 state/iss，应用会回 400「回调缺少参数」。
        """
        for _ in range(max_hops):
            if resp.status_code != 200 or len(resp.text) > 20000:
                return resp
            nxt = None
            for pat in _AUTO_REDIRECT_RES:
                m = pat.search(resp.text)
                if m:
                    nxt = html.unescape(m.group(1))
                    break
            if not nxt:
                return resp
            resp = self.session.get(nxt, timeout=self.timeout, allow_redirects=True)
        return resp

    def _finish(self, post: requests.Response) -> bool:
        self.result = post
        if post.status_code in (301, 302, 303, 307, 308):
            nxt = post.headers.get("location", "")
            self.redirect_to = nxt
            m = re.search(r"[?&]ticket=([^&]+)", nxt)
            if m:
                self.ticket = unquote(m.group(1))
            if nxt:
                self.result = self.session.get(nxt, timeout=self.timeout, allow_redirects=True)
        self.result = self._follow_client_redirects(self.result)
        self.error = None
        return True

    # ---- 对外 ----

    def login_service(self, service: str, retries: int = 1) -> bool:
        """service 直接是 CAS 注册的服务地址。"""
        self.cas_service = service
        self.error = None
        param = service if "%" in service else quote(service, safe="")
        for attempt in range(max(1, retries)):
            try:
                resp = self.session.get(f"{LOGIN_URL}?service={param}", timeout=self.timeout)
                resp.raise_for_status()
                form = self._parse_form(resp.text)
            except (requests.RequestException, LoginError) as exc:
                self.error = f"获取登录页失败: {exc}"
                if attempt + 1 < retries:
                    time.sleep(2)
                    continue
                return False
            try:
                post = self._submit(form)
            except requests.RequestException as exc:
                self.error = f"提交登录失败: {exc}"
                if attempt + 1 < retries:
                    time.sleep(2)
                    continue
                return False
            reason = self._failure_reason(post)
            if reason:
                self.error = reason
                self.result = post
                return False
            return self._finish(post)
        return False

    def login_entry(self, entry_url: str, retries: int = 1) -> bool:
        """从应用的「统一身份认证登录」入口走完整链路（OIDC / PKCE 应用用这个）。"""
        self.error = None
        for attempt in range(max(1, retries)):
            try:
                resp = self.session.get(entry_url, timeout=self.timeout, allow_redirects=True)
                if "/cas/login" not in resp.url:
                    self.error = f"入口没跳到 CAS 登录页，停在 {resp.url}"
                    return False
                m = re.search(r"[?&]service=([^&]+)", resp.url)
                self.cas_service = unquote(m.group(1)) if m else None
                form = self._parse_form(resp.text)
            except (requests.RequestException, LoginError) as exc:
                self.error = f"打开登录入口失败: {exc}"
                if attempt + 1 < retries:
                    time.sleep(2)
                    continue
                return False
            try:
                post = self._submit(form)
            except requests.RequestException as exc:
                self.error = f"提交登录失败: {exc}"
                if attempt + 1 < retries:
                    time.sleep(2)
                    continue
                return False
            reason = self._failure_reason(post)
            if reason:
                self.error = reason
                self.result = post
                return False
            return self._finish(post)
        return False

    def whoami(self) -> dict:
        """用票据向 CAS 校验，取回身份与认证强度。票据不绑定 service，可复用。"""
        if not self.ticket:
            return {}
        r = self.session.get(
            f"{CAS_BASE}/p3/serviceValidate",
            params={"service": self.cas_service or "https://www.ustc.edu.cn/",
                    "ticket": self.ticket, "format": "JSON"},
            timeout=self.timeout,
        )
        try:
            return r.json().get("serviceResponse", {})
        except ValueError:
            return {"raw": r.text[:200]}


# --------------------------------------------------------------------------- CLI


def _report(lg: UstcLogin, ok: bool, whoami: bool) -> None:
    print(f"结果: {'成功' if ok else '失败'}")
    if not ok:
        print(f"原因: {lg.error}")
        if lg.result is not None and lg.result.status_code == 401:
            print("提示: 口令错误不要反复重试，会触发账号锁定。")
        return
    print(f"票据: {(lg.ticket or '')[:12]}…  （拿到 ST- 票据 = CAS 认可了账号口令）")
    print(f"落点: {redact(lg.result.url if lg.result is not None else '')}  "
          f"HTTP {lg.result.status_code if lg.result is not None else '?'}")
    print(f"cookies: {sorted({c.name for c in lg.session.cookies})}")
    if not whoami:
        return
    data = lg.whoami()
    succ = data.get("authenticationSuccess")
    if not succ:
        print(f"whoami: {json.dumps(data, ensure_ascii=False)[:200]}")
        return
    attrs = succ.get("attributes", {})
    user = succ.get("user", "")
    masked = user[:4] + "*" * max(0, len(user) - 6) + user[-2:] if len(user) > 6 else "***"
    print(f"身份: {masked}")
    # 认证强度字段只在部分链路上回传：OIDC/OAuth2 桥接走的是另一套属性映射。
    method = "".join(attrs.get("samlAuthenticationStatementAuthMethod", []))
    if not method:
        credential = "".join(attrs.get("credentialType", []))
        method = f"{credential}（该链路未回传 SAML 认证强度）" if credential else ""
    if method:
        print(f"认证强度: {method}")
        if method.endswith("am:password"):
            print("          → am:password = 单因子（账号+口令），当前没有二次验证")
    # 只列属性名，不列值：这里可能含姓名、邮箱、学号等个人信息。
    print(f"可用属性: {', '.join(sorted(attrs))}（值可能含姓名/邮箱等个人信息，不要整包外传）")


def main(argv: Optional[list[str]] = None) -> int:
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="登录中国科大统一身份认证（仅限本人账号）")
    ap.add_argument("--env", default=os.path.join(skill_dir, ".env"), help="配置文件路径")
    ap.add_argument("--service", help="覆盖 USTC_SERVICE（CAS 服务地址）")
    ap.add_argument("--entry", help="覆盖 USTC_ENTRY（应用统一登录入口）")
    ap.add_argument("--timeout", type=int, default=0)
    ap.add_argument("--whoami", action="store_true", help="登录后调 serviceValidate 显示身份与认证强度")
    args = ap.parse_args(argv)

    cfg = load_env(args.env)
    username = cfg.get("USTC_USERNAME", "").strip()
    password = cfg.get("USTC_PASSWORD", "")
    service = (args.service or cfg.get("USTC_SERVICE", "")).strip()
    entry = (args.entry or cfg.get("USTC_ENTRY", "")).strip()
    timeout = args.timeout or int(cfg.get("USTC_TIMEOUT", "20") or 20)

    missing = [n for n, v in (("USTC_USERNAME", username), ("USTC_PASSWORD", password)) if not v.strip()]
    if missing:
        print(f"配置文件 {args.env} 里 {', '.join(missing)} 还是空的，先填。", file=sys.stderr)
        return 2
    if not service and not entry:
        print("USTC_SERVICE 和 USTC_ENTRY 至少填一个。", file=sys.stderr)
        return 2

    lg = UstcLogin(username, password, timeout=timeout)
    if entry:
        print(f"方式: entry  {entry}")
        ok = lg.login_entry(entry)
    else:
        print(f"方式: service {service}")
        ok = lg.login_service(service)
    _report(lg, ok, args.whoami)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
