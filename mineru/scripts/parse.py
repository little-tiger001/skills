#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 官方 API 文档解析脚本（仅用 Python 标准库，无需安装依赖）。

流程（对每个输入文件）：
  1. POST /api/v4/file-urls/batch  申请签名上传 URL，得到 batch_id
  2. PUT  文件字节到签名 URL
  3. 轮询 GET /api/v4/extract-results/batch/{batch_id} 直到 state=done
  4. 下载 full_zip_url（zip 包）
  5. 解压，定位 full.md 与图片
  6. 写入 ./.mineru/<文件名>.md，图片写入 ./.mineru/img/，并改写 md 图片路径

用法：
  python parse.py <文件1> [文件2 ...] [--ocr] [--no-table] [--no-formula]
                  [--model vlm|pipeline] [--language ch] [--timeout 600]
"""

import argparse
import http.client
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path
from urllib.parse import urlparse

API_BASE = "https://mineru.net/api/v4"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_env(env_path: Path) -> dict:
    """解析简单的 KEY=VALUE 格式 .env 文件。"""
    cfg = {}
    if not env_path.exists():
        return cfg
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def http_request(url: str, data: bytes = None, headers: dict = None,
                 method: str = None, timeout: int = 120):
    """发起 HTTP 请求，返回 (status_code, response_bytes)。"""
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误: {e.reason}")


def post_json(url: str, payload: dict, token: str, timeout: int = 120):
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    status, raw = http_request(url, data=body, headers=headers,
                               method="POST", timeout=timeout)
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, {"raw": raw.decode("utf-8", "replace")}


def get_json(url: str, token: str, timeout: int = 120):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    status, raw = http_request(url, headers=headers, method="GET",
                               timeout=timeout)
    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, {"raw": raw.decode("utf-8", "replace")}


def put_bytes(url: str, data: bytes, timeout: int = 300):
    """用 http.client 直接 PUT 上传，不附加 Content-Type 头。

    MinerU 的 OSS 签名 URL 是按「无 Content-Type」计算的，
    urllib 会自动加 Content-Type 导致 SignatureDoesNotMatch，
    因此这里手动构造请求以精确控制请求头。
    """
    parsed = urlparse(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" \
        else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
                    timeout=timeout)
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    try:
        conn.putrequest("PUT", path, skip_accept_encoding=True)
        conn.putheader("Content-Length", str(len(data)))
        conn.endheaders()
        conn.send(data)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# 解析单个文件
# --------------------------------------------------------------------------- #
def submit_and_upload(file_path: Path, token: str, model: str, language: str,
                      is_ocr: bool, enable_table: bool, enable_formula: bool):
    """申请上传 URL 并上传文件，返回 batch_id。"""
    payload = {
        "files": [{"name": file_path.name, "data_id": file_path.stem}],
        "model_version": model,
        "language": language,
        "enable_table": enable_table,
        "enable_formula": enable_formula,
        "is_ocr": is_ocr,
    }
    status, res = post_json(f"{API_BASE}/file-urls/batch", payload, token)
    if status != 200 or res.get("code") != 0:
        raise RuntimeError(f"申请上传 URL 失败 (HTTP {status}): {res}")

    batch_id = res["data"]["batch_id"]
    file_urls = res["data"]["file_urls"]
    if not file_urls:
        raise RuntimeError("未返回上传 URL")

    # PUT 上传文件（不附加 Content-Type，避免 OSS 签名不匹配）
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    status, raw = put_bytes(file_urls[0], file_bytes)
    if status not in (200, 201):
        raise RuntimeError(f"文件上传失败 (HTTP {status}): {raw[:300]!r}")
    return batch_id


def poll_batch(batch_id: str, token: str, timeout: int, interval: int = 5):
    """轮询批量任务，返回 extract_result 列表。"""
    url = f"{API_BASE}/extract-results/batch/{batch_id}"
    start = time.time()
    while time.time() - start < timeout:
        status, res = get_json(url, token)
        if status != 200 or res.get("code") != 0:
            raise RuntimeError(f"查询任务失败 (HTTP {status}): {res}")
        results = res["data"].get("extract_result", [])
        if not results:
            time.sleep(interval)
            continue

        pending = [r for r in results
                   if r.get("state") not in ("done", "failed")]
        if not pending:
            return results

        # 打印进度
        prog = pending[0].get("extract_progress", {})
        if prog:
            print(f"    解析中... {prog.get('extracted_pages', '?')}/"
                  f"{prog.get('total_pages', '?')} 页")
        else:
            print(f"    状态: {pending[0].get('state')}")
        time.sleep(interval)
    raise TimeoutError(f"轮询超时 ({timeout}s)，batch_id={batch_id}")


def rewrite_image_refs(md: str, base_to_new: dict) -> str:
    """把 md 中图片引用改写为 img/<新名>。"""
    def repl(m):
        alt = m.group(1)
        path = m.group(2)
        p = path.split()[0].strip()  # 去掉可能的 "title"
        base = os.path.basename(p)
        if base in base_to_new:
            return f"![{alt}](img/{base_to_new[base]})"
        return m.group(0)
    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", repl, md)


def relative_source_path(file_path: Path, workspace_root: Path) -> str:
    """返回相对工作区根目录的路径。"""
    try:
        return file_path.relative_to(workspace_root).as_posix()
    except ValueError:
        return file_path.name


def output_stem(file_path: Path, workspace_root: Path) -> str:
    """将相对路径扁平化为输出文件名，避免不同目录下同名文件覆盖。"""
    relative_path = relative_source_path(file_path, workspace_root)
    return Path(relative_path).with_suffix("").as_posix().replace("/", "-")


def process_file(file_path: Path, out_dir: Path, img_dir: Path,
                 workspace_root: Path,
                 token: str, model: str, language: str, is_ocr: bool,
                 enable_table: bool, enable_formula: bool, timeout: int):
    """解析单个文件，返回 (md_path, image_count)。"""
    stem = output_stem(file_path, workspace_root)
    print(f"  [1/4] 提交并上传: {file_path.name}")
    batch_id = submit_and_upload(file_path, token, model, language,
                                 is_ocr, enable_table, enable_formula)

    print(f"  [2/4] 等待解析完成 (batch_id={batch_id})")
    results = poll_batch(batch_id, token, timeout)
    result = results[0]
    if result.get("state") != "done":
        raise RuntimeError(f"解析失败: {result.get('err_msg', result)}")
    zip_url = result["full_zip_url"]

    print(f"  [3/4] 下载并解压结果")
    status, zip_bytes = http_request(zip_url, method="GET", timeout=300)
    if status != 200:
        raise RuntimeError(f"下载结果失败 (HTTP {status})")

    md_content = None
    base_to_new = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        # 定位 full.md
        md_name = next((n for n in names if n.split("/")[-1] == "full.md"), None)
        if not md_name:
            raise RuntimeError("结果包中未找到 full.md")
        md_content = zf.read(md_name).decode("utf-8", "replace")

        # 收集图片
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext in IMAGE_EXTS:
                base = os.path.basename(n)
                new_name = f"{stem}_{base}"
                base_to_new[base] = new_name
                with open(img_dir / new_name, "wb") as out:
                    out.write(zf.read(n))

    print(f"  [4/4] 写入 Markdown 与图片")
    md_content = rewrite_image_refs(md_content, base_to_new)
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(md_content, encoding="utf-8")
    return md_path, len(base_to_new)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="MinerU 文档解析")
    parser.add_argument("files", nargs="+", help="要解析的文件路径")
    parser.add_argument("--ocr", action="store_true", help="开启 OCR（扫描件）")
    parser.add_argument("--no-table", action="store_true", help="关闭表格识别")
    parser.add_argument("--no-formula", action="store_true", help="关闭公式识别")
    parser.add_argument("--model", default=None, help="vlm 或 pipeline")
    parser.add_argument("--language", default=None, help="解析语言，如 ch")
    parser.add_argument("--timeout", type=int, default=600, help="轮询超时秒数")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parent.parent
    cfg = load_env(skill_dir / ".env")

    token = cfg.get("MINERU_TOKEN", "").strip()
    if not token:
        print("错误: 未配置 MINERU_TOKEN。请在 skill 目录的 .env 文件中填写 "
              "MINERU_TOKEN（获取地址 https://mineru.net/apiManage/token）。")
        sys.exit(1)

    model = args.model or cfg.get("MINERU_MODEL", "vlm")
    language = args.language or cfg.get("MINERU_LANGUAGE", "ch")
    is_ocr = args.ocr
    enable_table = not args.no_table
    enable_formula = not args.no_formula

    # 输出目录：当前工作区根目录下的 .mineru
    out_dir = Path.cwd() / ".mineru"
    img_dir = out_dir / "img"
    out_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {out_dir}")
    print(f"模型: {model} | 语言: {language} | OCR: {is_ocr} | "
          f"表格: {enable_table} | 公式: {enable_formula}")
    print("=" * 60)

    ok_count = 0
    for fp in args.files:
        file_path = Path(fp).resolve()
        if not file_path.exists():
            print(f"\n[跳过] 文件不存在: {file_path}")
            continue
        print(f"\n▶ 解析: {file_path.name}")
        try:
            md_path, img_count = process_file(
                file_path, out_dir, img_dir, Path.cwd(), token, model, language,
                is_ocr, enable_table, enable_formula, args.timeout)
            rel_md = f".mineru/{md_path.name}"
            ok_count += 1
            print(f"  ✓ 完成: {rel_md} (图片 {img_count} 张)")
        except Exception as e:
            print(f"  ✗ 失败: {e}")

    print("=" * 60)
    print(f"全部完成: 成功 {ok_count}/{len(args.files)} 个文件")
    if ok_count == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
