---
name: ustc-passport-login
description: 用脚本登录中国科大统一身份认证（id.ustc.edu.cn / passport.ustc.edu.cn，锐捷 RG-SourceID 定制版），取得 CAS 票据与带登录态的 requests.Session，进而访问校内应用的受保护页面。支持三种形态：CAS 直连服务、ITDR 网关服务（教务）、应用自有 OIDC+PKCE 入口（词元工坊）。用户提到科大统一身份认证、CAS 登录、自动登录校内系统、拿 ST 票据、登录教务 jw、登录词元工坊、登录校园应用时使用。
---

# 登录中国科大统一身份认证

## 凭据

- 在本 skill 目录的 `.env` 里：`USTC_USERNAME` / `USTC_PASSWORD` / `USTC_SERVICE` / `USTC_ENTRY`，用前先读。
- 该目录是共享技能仓库，`.gitignore` 已忽略 `.env`（`**/.env`）。**绝不**把口令写进 `SKILL.md`、回复、日志或任何会被提交的文件。
- 票据 `ST-…` 是一次性凭据，打印前打码。
- 账号仅限本人使用；学校规定外借、共享、委托他人登录属违规。只为本人账号执行。

## 用法

```bash
python scripts/ustc_login.py --whoami        # 登录 + 显示身份与认证强度（先跑这个验证）
python scripts/ustc_login.py                 # 只登录，打印票据与落点
python scripts/ustc_login.py --service https://www.ustc.edu.cn/
python scripts/ustc_login.py --entry https://id.ustc.edu.cn/tokenworks/credits/auth/login
```

需要拿登录态做后续操作时，在 Python 里 `from ustc_login import UstcLogin`，登录后复用 `lg.session`（带着 TGC 与各应用自己的 cookie）。

## 选对登录目标（成败关键）

| 形态 | 填哪个 | 已知可用值 |
|---|---|---|
| CAS 直连 | `USTC_SERVICE` | `https://www.ustc.edu.cn/`、`https://weixine.ustc.edu.cn/2020/caslogin` |
| ITDR 网关 | `USTC_SERVICE` | `https://jw.ustc.edu.cn/ucas-sso/login` |
| OIDC + PKCE | `USTC_ENTRY` | `https://id.ustc.edu.cn/tokenworks/credits/auth/login` |

**不要猜 service**：裸域名基本都被拒（`canot-access-code=1510051`「应用未对接认证服务」），但那不代表应用没接统一认证。正确做法是打开应用，找「统一身份认证登录」按钮，抄它的真实链接（例如教务首页的按钮指向 `/ucas-sso/login`）。

## 判成功与判失败

- **唯一可靠的成功信号：拿到 `ST-…` 票据**。页面返回 200 不算数——匿名也可能 200。
- 想确认真的进了目标应用，做**对照实验**：同一个 URL 用匿名 session 和登录后 session 各请求一次，看是否被弹回登录页、页面里是否出现本人身份信息、页面大小是否变化。
- **401 = 口令或账号错误**。不要重试，会累计失败次数触发账号锁定。
- 302 回登录页并带 `exception.message=Error decoding flow execution` = 流程令牌坏了，重新取登录页即可。
- 认证强度看 `--whoami` 输出：`urn:oasis:names:tc:SAML:*:am:password` 即单因子、无二次验证。当前平台单因子；但风控/设备指纹与挑战端点存在，若被启用本方案会立即失效。

## 协议要点（脚本已实现，不要手搓）

- 登录页服务端渲染两个值：`<p id="login-croypto">`（会话级 AES-128 密钥）与 `<p id="login-page-flowkey">`（execution 令牌），两者每次渲染都变，必须同 session 使用。
- 口令加密：`base64(AES-128-ECB/PKCS7(base64decode(croypto), 口令))`。已与站点自带 CryptoJS 逐字节对齐。
- `riskSystemSwitch=USTC` 时随表单带 `risk_payload`/`targetSystem`/`siteId`/`riskEngine`，但**服务端不强制**：风控指纹与 ITDR 的 `itdr_verify_token` 漏掉照样发票。
- OIDC 应用收尾的 `/doc/oidc/callback` **不用 302**，而是 `<meta http-equiv=refresh>` + `window.location.replace()` 跳转；那段 meta 的 URL 含 HTML 实体 `&amp;`，必须取到引号闭合处再反转义（截断会丢 `state`/`iss`，应用回 400「回调缺少参数」）。
- 失效/不可用：旧 `passport.ustc.edu.cn/validatecode.jsp` 已 404（验证码取消）；`/cas/v1/tickets`（REST）被网关打回 403。
- `p3/serviceValidate` 的返回随链路变形：普通 CAS 服务会回 `samlAuthenticationStatementAuthMethod`（值为 `urn:oasis:names:tc:SAML:*:am:password`，可据此判单因子）；OIDC/OAuth2 桥接**不回这个字段**，改回一套自有映射（`XH` / `gid` / `name` / `email` / `deptCode` …）。所以 `--whoami` 在两条链路上的输出不同，且**那套属性含姓名、邮箱等个人信息，只列属性名，不要整包打印或外传**。

## 注意

- 全程只读：登录本身不改动任何数据。拿到 session 后**不要**替用户点「领取」「提交」这类会改变状态的操作，除非用户明确要求。
- 输出页面正文前先过滤，别把用户姓名、学号、邮箱等个人信息打进对话或日志。
