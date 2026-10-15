#!/usr/bin/env python3
"""
cu_ui.py - Windows UI Automation engine for WorkBuddy computer-use.

ZERO DEPENDENCIES -- the whole point
------------------------------------
This engine is built on the Win32 API through ctypes only -- no pywin32, no
comtypes, no uiautomation package, nothing to pip install. That keeps it
portable: drop the folder anywhere, run it with any Python 3.8+, and it works.
Nothing needs to be downloaded at install time or at run time.

Two layers:

  1. STRUCTURED TREE (preferred, safe)
     Enumerate windows by HWND via EnumChildWindows, print a tree where every
     line carries a stable integer index, then act on an element by that index.
     Works great for native Win32 apps (Notepad, Calculator, File dialogs,
     Explorer panes, most LOB apps).

  2. COORDINATE FALLBACK (for self-drawn UIs)
     WeChat, Electron, Qt, Flutter and games draw their content on a single
     canvas with no per-control HWNDs, so the tree collapses to nested empty
     Groups. There is nothing to index, so we fall back to SetCursorPos +
     mouse_event at a window-normalized 0-1000 point. A stale pixel is less
     dangerous than a stale index because we re-resolve the window frame on
     every call -- but always confirm the effect with `shot`.

The same rules inherited from the reference spec hold:
  * The index is the integer at the START of a tree line, NOT a line number.
  * Indices go stale on every transition. Re-read the tree after one.
  * `ok:true` is not proof. Proof is the next tree showing the target state.

The JSONL bridge protocol (all files live in %TEMP%):
  %TEMP%/cu_cmd.jsonl    agent appends one JSON line per command
  %TEMP%/cu_status.json  result of the last command
  %TEMP%/cu_tree.txt     full output of the last `tree`
  %TEMP%/cu_alive         heartbeat: "<pid> <session_ok>"
  %TEMP%/cu_stop          touch it to stop the bridge
  %TEMP%/cu_shot.bmp      last screenshot (BMP)
"""

import os
import sys
import json
import time
import struct
import argparse
import ctypes
import ctypes.wintypes as w

if sys.platform != "win32":
    print(json.dumps({"ok": False, "error": "not_windows",
                      "detail": "cu_ui.py is the Windows engine; run it on Windows."},
                     ensure_ascii=False, indent=2))
    sys.exit(3)

# --------------------------------------------------------------------------
# Win32 bindings (ctypes only)
# --------------------------------------------------------------------------
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32
psapi = ctypes.windll.psapi

HWND = c_void_p = ctypes.c_void_p
LONG_PTR = ctypes.c_int64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_int32
DWORD = ctypes.c_uint
BOOL = ctypes.c_bool
UINT = ctypes.c_uint

# DPI awareness so GetWindowRect / SetCursorPos agree on physical pixels.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

# --- constants -------------------------------------------------------------
WM_SETTEXT = 0x000C
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_CHAR = 0x0102
BM_CLICK = 0x00F5
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_VSCROLL = 0x0115
WM_HSCROLL = 0x0114
WM_MOUSEWHEEL = 0x020A
SB_LINEUP = 0
SB_LINEDOWN = 1
SB_PAGEUP = 2
SB_PAGEDOWN = 3
SB_TOP = 6
SB_BOTTOM = 7
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
EM_GETSEL = 0x00B0
GWL_STYLE = -16
WS_DISABLED = 0x08000000
WS_VISIBLE = 0x10000000
SW_RESTORE = 9
SM_CXSCREEN = 0
SM_CYSCREEN = 1
UOI_NAME = 2

# mouse_event flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002

# --- argument types --------------------------------------------------------
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [HWND, ctypes.c_wchar_p, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(w.RECT)]
user32.GetWindowRect.restype = ctypes.c_int
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindowVisible.restype = BOOL
user32.IsWindowEnabled.argtypes = [HWND]
user32.IsWindowEnabled.restype = BOOL
user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.SendMessageW.argtypes = [HWND, UINT, ctypes.c_void_p, ctypes.c_void_p]
user32.SendMessageW.restype = ctypes.c_int64
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = BOOL
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.ShowWindow.restype = BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = BOOL
user32.GetCursorPos.argtypes = [ctypes.POINTER(w.POINT)]
user32.GetCursorPos.restype = BOOL
user32.mouse_event.argtypes = [DWORD, DWORD, DWORD, ctypes.c_int, ctypes.c_void_p]
user32.mouse_event.restype = None
user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, DWORD, ctypes.c_void_p]
user32.keybd_event.restype = None
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = HWND
user32.GetDesktopWindow.argtypes = []
user32.GetDesktopWindow.restype = HWND
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetProcessWindowStation.argtypes = []
user32.GetProcessWindowStation.restype = HWND
user32.GetUserObjectInformationW.argtypes = [HWND, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(DWORD)]
user32.GetUserObjectInformationW.restype = BOOL

WINFUNC = ctypes.WINFUNCTYPE(BOOL, HWND, ctypes.c_void_p)
WINFUNCTYPE = ctypes.WINFUNCTYPE

kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HWND
PROCESS_QUERY = 0x0400 | 0x0010  # QUERY_INFORMATION | VM_READ
psapi.GetModuleBaseNameW.argtypes = [HWND, HWND, ctypes.c_wchar_p, DWORD]
psapi.GetModuleBaseNameW.restype = DWORD
kernel32.CloseHandle.argtypes = [HWND]
kernel32.CloseHandle.restype = BOOL

# GetDC / ReleaseDC are exported by user32 (not gdi32)
user32.GetDC.argtypes = [HWND]
user32.GetDC.restype = HWND
user32.ReleaseDC.argtypes = [HWND, HWND]
user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [HWND]
gdi32.CreateCompatibleDC.restype = HWND
gdi32.CreateCompatibleBitmap.argtypes = [HWND, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = HWND
gdi32.SelectObject.argtypes = [HWND, HWND]
gdi32.SelectObject.restype = HWND
gdi32.BitBlt.argtypes = [HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         HWND, ctypes.c_int, ctypes.c_int, DWORD]
gdi32.BitBlt.restype = BOOL
gdi32.GetDIBits.argtypes = [HWND, HWND, DWORD, DWORD, ctypes.c_void_p,
                            ctypes.c_void_p, DWORD]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [HWND]
gdi32.DeleteObject.restype = BOOL
gdi32.DeleteDC.argtypes = [HWND]
gdi32.DeleteDC.restype = BOOL

# --------------------------------------------------------------------------
# Role mapping (HWND class name -> friendly role)
# --------------------------------------------------------------------------
CLASS_ROLE = {
    "Button": "Button", "Edit": "Edit", "RichEdit20W": "Edit", "RICHEDIT50W": "Edit",
    "ComboBox": "ComboBox", "ComboBoxEx32": "ComboBox", "ListBox": "List",
    "SysListView32": "List", "SysListBox32": "List", "Static": "StaticText",
    "SysTreeView32": "Tree", "SysTabControl32": "Tab", "msctls_trackbar32": "Slider",
    "ScrollBar": "ScrollBar", "msctls_updown32": "Spinner", "ToolbarWindow32": "Toolbar",
    "ReBarWindow32": "ReBar", "SysDateTimePick32": "DatePicker", "SysMonthCal32": "Calendar",
    "msctls_progress32": "ProgressBar", "SysLink": "Link", "SysHeader32": "Header",
    "ComboLBox": "List", "ListBoxX": "List",
}
TOPLEVEL_ROLE = "Window"
GROUPBOX_STYLE = 0x0007  # BS_GROUPBOX


def friendly_role(hwnd, cls):
    try:
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    except Exception:
        style = 0
    if cls == "Button" and (style & 0x0F) == GROUPBOX_STYLE:
        return "Group"
    if cls in CLASS_ROLE:
        return CLASS_ROLE[cls]
    return "Control"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def get_text(hwnd):
    # Use the WM_GETTEXT message directly. GetWindowTextW() sends the same
    # message but enforces a cross-thread timeout and returns "" for child
    # controls owned by another thread (e.g. Notepad's edit). The message
    # form blocks on the control's own thread and returns the real text.
    try:
        L = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    except Exception:
        L = 0
    if L <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(L + 2)
    user32.SendMessageW(hwnd, WM_GETTEXT, L + 1, buf)
    return buf.value or ""


def get_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 255)
    return buf.value or ""


def get_pid(hwnd):
    pid = DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_exe(pid):
    if not pid:
        return ""
    try:
        h = kernel32.OpenProcess(PROCESS_QUERY, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(512)
        psapi.GetModuleBaseNameW(h, None, buf, 511)
        kernel32.CloseHandle(h)
        return (buf.value or "").lower()
    except Exception:
        return ""


def rect_of(hwnd):
    r = w.RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return [r.left, r.top, r.right, r.bottom]
    return None


def centre_of(frame):
    if not frame:
        return None
    x0, y0, x1, y1 = frame
    return [(x0 + x1) / 2.0, (y0 + y1) / 2.0]


# --------------------------------------------------------------------------
# Session detection (can we reach the interactive desktop?)
# --------------------------------------------------------------------------
_SESSION = {"ok": False, "station": None, "detail": ""}


def check_session():
    """Detect whether this process can reach the interactive desktop.

    On Windows this means being attached to the interactive window station
    WinSta0 in the current user's session. A process spawned from a
    non-interactive context (a Windows service, a scheduled task registered
    without /IT, some CI runners) still enumerates *something* but CANNOT post
    input to the real desktop -- its window list is empty or foreign. Run
    `probe` first: if it reports session_ok:false, launch the bridge with
    start_cu_bridge.bat from the user's own interactive session.
    """
    if _SESSION["ok"]:
        return _SESSION["ok"]
    try:
        hws = user32.GetProcessWindowStation()
        buf = ctypes.create_unicode_buffer(256)
        needed = DWORD(0)
        ok = user32.GetUserObjectInformationW(hws, UOI_NAME, buf, 256 * 2,
                                              ctypes.byref(needed))
        station = buf.value if ok else ""
        _SESSION["station"] = station
        if station != "WinSta0":
            _SESSION["detail"] = (
                "Process is on window station '%s', not WinSta0. It cannot "
                "reach the interactive desktop, so it can read its own (likely "
                "empty) window list but cannot move the mouse or send keys to "
                "real windows. Run start_cu_bridge.bat from your interactive "
                "user session (double-click it, or use the Task Scheduler "
                "'At logon' task) and talk to it through the %TEMP% files."
                % station)
            _SESSION["ok"] = False
            return False
        # WinSta0 present: confirm we can see real windows.
        found = []
        cb = WINFUNC(lambda hwnd, _: (found.append(hwnd) or True))
        user32.EnumWindows(cb, 0)
        # keep a reference alive during the call
        check_session._keep = cb
        visible = [h for h in found
                   if user32.IsWindowVisible(h) and get_text(h)]
        _SESSION["ok"] = True
        _SESSION["visible_windows"] = len(visible)
        return True
    except Exception as e:
        _SESSION["detail"] = "session check failed: %s" % e
        _SESSION["ok"] = False
        return False


def require_session(cmd_name=""):
    if check_session():
        return None
    out = {"ok": False, "cmd": cmd_name, "error": "no_gui_session",
           "station": _SESSION.get("station"),
           "detail": _SESSION.get("detail")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(3)


# --------------------------------------------------------------------------
# App resolution
# --------------------------------------------------------------------------
def _enum_top_windows():
    found = []

    def cb(hwnd, _):
        found.append(hwnd)
        return True
    fn = WINFUNCTYPE(BOOL, HWND, ctypes.c_void_p)(cb)
    user32.EnumWindows(fn, 0)
    _enum_top_windows._keep = fn
    return found


def running_apps():
    """List running apps as [(pid, name, exe)]."""
    out = []
    seen = set()
    for hwnd in _enum_top_windows():
        if not user32.IsWindowVisible(hwnd):
            continue
        t = get_text(hwnd)
        if not t:
            continue
        pid = get_pid(hwnd)
        if pid in seen:
            continue
        seen.add(pid)
        exe = get_exe(pid)
        name = exe.replace(".exe", "") if exe else t
        out.append((pid, name, exe))
    out.sort(key=lambda d: (d[1] or "").lower())
    return out


def resolve_app(token):
    """token: pid (int), exact name, substring of name, or exe name."""
    apps = running_apps()
    try:
        pid = int(token)
        for p, n, e in apps:
            if p == pid:
                return pid, n, e
        return pid, token, ""
    except ValueError:
        pass
    low = token.lower()
    for p, n, e in apps:
        if n and n.lower() == low:
            return p, n, e
    for p, n, e in apps:
        if e and e.lower() == low:
            return p, n, e
    for p, n, e in apps:
        if n and low in n.lower():
            return p, n, e
    return None, None, None


def top_hwnds_for_pid(pid):
    res = []
    for hwnd in _enum_top_windows():
        if user32.IsWindowVisible(hwnd) and get_pid(hwnd) == pid:
            res.append(hwnd)
    return res


# --------------------------------------------------------------------------
# Tree building (HWND enumeration, DFS pre-order)
# --------------------------------------------------------------------------
class Node:
    __slots__ = ("idx", "hwnd", "role", "cls", "title", "frame", "enabled",
                 "visible", "depth", "parent", "childcount")

    def __init__(self):
        self.idx = -1
        self.hwnd = 0
        self.role = ""
        self.cls = ""
        self.title = ""
        self.frame = None
        self.enabled = None
        self.visible = None
        self.depth = 0
        self.parent = -1
        self.childcount = 0


SKIP_VIRTUAL = {"#32769"}  # desktop window class


def collect_descendants(hwnd, acc):
    acc.append(hwnd)
    kids = []

    def cb(child, _):
        kids.append(child)
        return True
    fn = WINFUNCTYPE(BOOL, HWND, ctypes.c_void_p)(cb)
    user32.EnumChildWindows(hwnd, fn, 0)
    collect_descendants._keep = getattr(collect_descendants, "_keep", [])
    collect_descendants._keep.append(fn)
    for k in kids:
        collect_descendants(k, acc)


def build_tree(pid, depth=12, max_nodes=400):
    nodes = []
    windows = []  # (node_idx, hwnd, title)
    tops = top_hwnds_for_pid(pid)
    if not tops:
        return nodes, windows
    # DFS over all top-level windows
    order = []
    for t in tops:
        collect_descendants(t, order)
    # assign indices in DFS order; cap
    index_of = {}
    for raw_i, hwnd in enumerate(order):
        if len(nodes) >= max_nodes:
            break
        cls = get_class(hwnd)
        if cls in SKIP_VIRTUAL:
            continue
        is_top = hwnd in tops
        n = Node()
        n.hwnd = int(hwnd)
        n.cls = cls
        n.title = get_text(hwnd)
        n.role = TOPLEVEL_ROLE if is_top else friendly_role(hwnd, cls)
        n.frame = rect_of(hwnd)
        try:
            n.enabled = bool(user32.IsWindowEnabled(hwnd))
        except Exception:
            n.enabled = None
        n.visible = bool(user32.IsWindowVisible(hwnd))
        n.depth = 0  # fixed below
        n.idx = len(nodes)
        index_of[hwnd] = n.idx
        nodes.append(n)
        if is_top:
            windows.append((n.idx, hwnd, n.title))
    # compute depth/parent from HWND parent chain
    for n in nodes:
        d = 0
        p = user32.GetParent(n.hwnd)
        # walk up using GetParent until we leave the app's node set
        cur = p
        chain = []
        while cur:
            chain.append(cur)
            cur = user32.GetParent(cur)
        # depth = number of ancestors that are in this app's node set
        depth_count = 0
        for anc in chain:
            if anc in index_of:
                depth_count += 1
        n.depth = depth_count
        # parent index
        par = user32.GetParent(n.hwnd)
        n.parent = index_of.get(par, -1)
    # childcount per node
    for n in nodes:
        c = 0
        for m in nodes:
            if m.parent == n.idx:
                c += 1
        n.childcount = c
    # prune by depth: keep only nodes whose depth <= depth
    if depth < 100:
        nodes = [n for n in nodes if n.depth <= depth]
        # reindex
        new_idx = {}
        for i, n in enumerate(nodes):
            new_idx[n.hwnd] = i
            n.idx = i
        for n in nodes:
            n.parent = new_idx.get(next((h for h, i2 in new_idx.items()
                                         if i2 == n.parent), None), -1) if n.parent >= 0 else -1
        for n in nodes:
            n.parent = new_idx.get(n.hwnd_parent_lookup(n, new_idx), -1) if False else n.parent
        # fix parent references properly
        hwnd_to_idx = {n.hwnd: n.idx for n in nodes}
        for n in nodes:
            par = user32.GetParent(n.hwnd)
            n.parent = hwnd_to_idx.get(par, -1)
        windows = [(hwnd_to_idx.get(h, -1), h, t) for (_, h, t) in windows
                   if h in hwnd_to_idx]
        windows = [(i, h, t) for (i, h, t) in windows if i >= 0]
    return nodes, windows


def Node_hwnd_parent_lookup(self, new_idx):
    return None


Node.hwnd_parent_lookup = Node_hwnd_parent_lookup


def norm1000(n, win_frame):
    c = centre_of(n.frame)
    if not c or not win_frame:
        return None
    x0, y0, x1, y1 = win_frame
    ww, wh = x1 - x0, y1 - y0
    if ww <= 0 or wh <= 0:
        return None
    return [int(round((c[0] - x0) / ww * 1000)),
            int(round((c[1] - y0) / wh * 1000))]


def fmt_tree(nodes, windows, show_actions=False, win_frame=None):
    lines = []
    for n in nodes:
        pad = "  " * n.depth
        label = n.title or ""
        seg = "%s[%d] %s" % (pad, n.idx, n.role)
        if label:
            seg += ' "%s"' % label
        if n.cls and n.cls not in ("Button", "Edit", "Static", "Window"):
            seg += " sub:%s" % n.cls
        if n.enabled is False:
            seg += " [disabled]"
        if not n.visible:
            seg += " [hidden]"
        lines.append(seg)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Input primitives (user32)
# --------------------------------------------------------------------------
def mouse_click_at(x, y):
    user32.SetCursorPos(int(round(x)), int(round(y)))
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.04)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    return True


def mouse_drag(x1, y1, x2, y2, steps=8):
    user32.SetCursorPos(int(round(x1)), int(round(y1)))
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, None)
    time.sleep(0.06)
    for i in range(1, steps + 1):
        t = i / float(steps)
        user32.SetCursorPos(int(round(x1 + (x2 - x1) * t)),
                            int(round(y1 + (y2 - y1) * t)))
        time.sleep(0.02)
    time.sleep(0.05)
    user32.SetCursorPos(int(round(x2)), int(round(y2)))
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, None)
    return True


def mouse_wheel(x, y, lines):
    user32.SetCursorPos(int(round(x)), int(round(y)))
    time.sleep(0.03)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(-120 * lines), None)
    return True


VK = {
    "return": 0x0D, "enter": 0x0D, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "escape": 0x1B, "esc": 0x1B,
    "left": 0x25, "right": 0x27, "down": 0x28, "up": 0x26,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "capital": 0x14,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def vk_of(ch):
    if "a" <= ch <= "z":
        return ord(ch) - ord("a") + 0x41
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 0x41
    if "0" <= ch <= "9":
        return ord(ch)
    return None


def key_down(vk):
    user32.keybd_event(vk & 0xFF, 0, 0, None)


def key_up(vk):
    user32.keybd_event(vk & 0xFF, 0, KEYEVENTF_KEYUP, None)


def send_keys_text(text):
    """Type text into the currently focused control (WM_CHAR to foreground)."""
    hw = user32.GetForegroundWindow()
    for ch in text:
        user32.SendMessageW(hw, WM_CHAR, ord(ch), 0)
        time.sleep(0.005)
    return True


def send_key_combo(combo):
    parts = [p for p in str(combo).split("+") if p]
    if not parts:
        return "bad_combo"
    key = parts[-1].lower()
    mods = [p.lower() for p in parts[:-1]]
    vk = VK.get(key)
    if vk is None:
        vk = vk_of(key)
        if vk is None:
            return "unknown_key:%s" % key
    mod_map = {"ctrl": 0x11, "control": 0x11, "shift": 0x10,
               "alt": 0x12, "menu": 0x12, "win": 0x5B, "lwin": 0x5B}
    for m in mods:
        if m not in mod_map:
            return "unknown_mod:%s" % m
    for m in mods:
        key_down(mod_map[m])
    time.sleep(0.02)
    key_down(vk)
    time.sleep(0.02)
    key_up(vk)
    for m in reversed(mods):
        key_up(mod_map[m])
    return True


# --------------------------------------------------------------------------
# Screenshot (BitBlt -> BMP)
# --------------------------------------------------------------------------
def capture_screen_bmp(path):
    ww = user32.GetSystemMetrics(SM_CXSCREEN)
    hh = user32.GetSystemMetrics(SM_CYSCREEN)
    hdc = user32.GetDC(0)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, ww, hh)
    gdi32.SelectObject(memdc, bmp)
    gdi32.BitBlt(memdc, 0, 0, ww, hh, hdc, 0, 0, 0x00CC0020)
    header = struct.pack("<IiiHHIIiiII", 40, ww, -hh, 1, 32, 0,
                         ww * hh * 4, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(ww * hh * 4)
    gdi32.GetDIBits(memdc, bmp, 0, hh, buf, header, 0)
    with open(path, "wb") as f:
        filesize = 14 + 40 + ww * hh * 4
        f.write(b"BM")
        f.write(struct.pack("<I", filesize))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", 54))
        f.write(header)
        f.write(buf.raw)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(0, hdc)
    return ww, hh


# --------------------------------------------------------------------------
# Stale-index guard
# --------------------------------------------------------------------------
_LAST_TREE = {}


def _tree_fp(nodes):
    return [(n.role, n.title, n.cls) for n in nodes]


def _remember(pid, nodes):
    _LAST_TREE[pid] = _tree_fp(nodes)


def _stale_check(args, pid, nodes, idx):
    if getattr(args, "force", False):
        return None
    prev = _LAST_TREE.get(pid)
    if not prev or idx >= len(prev) or idx >= len(nodes):
        return None
    if prev[idx] != _tree_fp(nodes)[idx]:
        n = nodes[idx]
        return {
            "ok": False, "code": "stale_index", "error": "stale_index",
            "idx": idx,
            "was": "%s %s" % (prev[idx][0], prev[idx][1] or ""),
            "now": "%s %s" % (n.role, n.title or ""),
            "detail": ("row identity changed since the previous tree - the UI "
                       "transitioned and this index now points elsewhere. "
                       "Re-read the tree and use the new index, or pass "
                       "--force to override deliberately."),
        }
    return None


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def cmd_probe(args):
    check_session()
    ok = _SESSION["ok"]
    focused_hwnd = user32.GetForegroundWindow()
    fpid = get_pid(focused_hwnd) if focused_hwnd else 0
    fname = get_text(focused_hwnd) if focused_hwnd else None
    if ok:
        verdict = "READY"
    else:
        verdict = "NO_GUI_SESSION"

    out = {
        "ok": ok, "verdict": verdict, "platform": "windows",
        "station": _SESSION.get("station"),
        "can_act": ok, "can_see": ok,
        "focused_app": fname, "focused_pid": fpid,
        "python": sys.executable, "pid": os.getpid(),
    }
    if verdict == "NO_GUI_SESSION":
        out["diagnosis"] = _SESSION.get("detail")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 3)


def cmd_apps(args):
    lst = [{"pid": p, "name": n, "exe": e} for p, n, e in running_apps()]
    print(json.dumps({"ok": True, "count": len(lst), "apps": lst},
                     ensure_ascii=False, indent=2))


def _nodes_for(args):
    pid, name, exe = resolve_app(args.app)
    if pid is None:
        print(json.dumps({"ok": False, "code": "app_not_found",
                          "error": "app_not_found", "token": args.app},
                         ensure_ascii=False))
        sys.exit(2)
    nodes, windows = build_tree(pid, depth=args.depth or 12,
                                max_nodes=args.max_nodes or 400)
    return pid, name, exe, nodes, windows


def cmd_tree(args):
    pid, name, exe, nodes, windows = _nodes_for(args)
    _remember(pid, nodes)
    win_frame = None
    for wi, _h, _t in windows:
        if wi < len(nodes) and nodes[wi].frame:
            win_frame = nodes[wi].frame
            break
    if args.json:
        out = [{
            "i": n.idx, "role": n.role, "sub": n.cls, "title": n.title,
            "enabled": n.enabled, "visible": n.visible, "frame": n.frame,
            "centre": centre_of(n.frame), "n1000": norm1000(n, win_frame),
            "depth": n.depth, "parent": n.parent,
        } for n in nodes]
        print(json.dumps({"ok": True, "app": name, "exe": exe, "pid": pid,
                          "count": len(out),
                          "windows": [{"idx": wi, "title": t}
                                      for wi, _, t in windows],
                          "nodes": out}, ensure_ascii=False, indent=2))
    else:
        print("app: %s (pid %s, exe %s)  windows: %d  nodes: %d"
              % (name, pid, exe, len(windows), len(nodes)))
        for wi, _, wt in windows:
            print("  window idx=%d %s" % (wi, ('"%s"' % wt) if wt else "(untitled)"))
        print(fmt_tree(nodes, windows, show_actions=args.actions))


def cmd_info(args):
    pid, name, exe, nodes, windows = _nodes_for(args)
    if args.idx >= len(nodes):
        print(json.dumps({"ok": False, "error": "index_out_of_range"},
                         ensure_ascii=False))
        sys.exit(2)
    n = nodes[args.idx]
    win_frame = None
    for wi, _, _ in windows:
        if wi < len(nodes) and nodes[wi].frame:
            win_frame = nodes[wi].frame
            break
    print(json.dumps({"ok": True, "idx": n.idx, "role": n.role, "sub": n.cls,
                      "title": n.title, "enabled": n.enabled,
                      "visible": n.visible, "frame": n.frame,
                      "centre": centre_of(n.frame),
                      "n1000": norm1000(n, win_frame),
                      "childcount": n.childcount, "depth": n.depth,
                      "app": name, "exe": exe, "pid": pid},
                     ensure_ascii=False, indent=2, default=str))


def _load_target(args, cmd):
    require_session(cmd)
    pid, name, exe, nodes, windows = _nodes_for(args)
    if args.idx >= len(nodes):
        _fail("index_out_of_range", "max_index=%d" % (len(nodes) - 1))
    stale = _stale_check(args, pid, nodes, args.idx)
    if stale:
        print(json.dumps(stale, ensure_ascii=False))
        sys.exit(2)
    _remember(pid, nodes)
    return pid, name, exe, nodes, windows, nodes[args.idx]


def cmd_click(args):
    pid, name, exe, nodes, windows, n = _load_target(args, "click")
    hwnd = n.hwnd
    method = None
    if n.cls == "Button":
        user32.SendMessageW(hwnd, BM_CLICK, 0, 0)
        method = "win:BM_CLICK"
        ok = True
    else:
        c = centre_of(n.frame)
        if not c:
            _fail("no_frame", "idx %d has no frame for a mouse click" % args.idx)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        mouse_click_at(c[0], c[1])
        method = "win:mouse"
        ok = True
    print(json.dumps({"ok": ok, "method": method, "idx": args.idx,
                      "role": n.role, "title": n.title, "hwnd": hwnd,
                      "app": name, "pid": pid}, ensure_ascii=False))


def cmd_set(args):
    pid, name, exe, nodes, windows, n = _load_target(args, "set")
    hwnd = n.hwnd
    if n.cls in ("Edit", "RichEdit20W", "RICHEDIT50W"):
        user32.SendMessageW(hwnd, WM_SETTEXT, 0, ctypes.c_wchar_p(args.text))
        method = "win:WM_SETTEXT"
        ok = True
    else:
        c = centre_of(n.frame)
        if not c:
            _fail("not_settable_no_frame", "idx %d has no frame" % args.idx)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        mouse_click_at(c[0], c[1])
        send_keys_text(args.text)
        method = "win:type"
        ok = True
    print(json.dumps({"ok": ok, "method": method, "idx": args.idx,
                      "role": n.role, "title": n.title, "text": args.text,
                      "app": name, "pid": pid}, ensure_ascii=False))


def cmd_launch(args):
    import subprocess
    tok = args.app
    errs = []
    launched = False
    # 1) path / exe via Popen
    try:
        if "/" in tok or "\\" in tok or tok.lower().endswith(".exe"):
            subprocess.Popen(tok)
            launched = True
        else:
            subprocess.Popen(tok)
            launched = True
    except Exception as e:
        errs.append("popen %s -> %s" % (tok, e))
    if not launched:
        # 2) os.startfile
        try:
            os.startfile(tok)
            launched = True
        except Exception as e:
            errs.append("startfile %s -> %s" % (tok, e))
    if not launched:
        print(json.dumps({"ok": False, "error": "launch_failed", "token": tok,
                          "detail": errs}, ensure_ascii=False, indent=2))
        sys.exit(2)
    time.sleep(max(0.0, float(getattr(args, "wait", 2.5) or 0)))
    pid, name, exe = resolve_app(tok)
    print(json.dumps({"ok": True, "pid": pid, "name": name, "exe": exe,
                      "via": tok}, ensure_ascii=False, indent=2))


def cmd_focus(args):
    require_session("focus")
    pid, name, exe = resolve_app(args.app)
    if pid is None:
        print(json.dumps({"ok": False, "error": "app_not_found",
                          "token": args.app}, ensure_ascii=False))
        sys.exit(2)
    tops = top_hwnds_for_pid(pid)
    if not tops:
        print(json.dumps({"ok": False, "error": "not_running", "pid": pid},
                         ensure_ascii=False))
        sys.exit(2)
    hw = tops[0]
    user32.ShowWindow(hw, SW_RESTORE)
    ok = bool(user32.SetForegroundWindow(hw))
    print(json.dumps({"ok": ok, "app": name, "pid": pid, "hwnd": int(hw)},
                     ensure_ascii=False))


def cmd_activate(args):
    """Windows: bring to front via SetForegroundWindow."""
    require_session("activate")
    pid, name, exe = resolve_app(args.app)
    if pid is None:
        print(json.dumps({"ok": False, "error": "app_not_found",
                          "token": args.app}, ensure_ascii=False))
        sys.exit(2)
    tops = top_hwnds_for_pid(pid)
    if not tops:
        print(json.dumps({"ok": False, "error": "not_running", "pid": pid},
                         ensure_ascii=False))
        sys.exit(2)
    hw = tops[0]
    user32.ShowWindow(hw, SW_RESTORE)
    ok = bool(user32.SetForegroundWindow(hw))
    print(json.dumps({"ok": ok, "app": name, "pid": pid, "hwnd": int(hw)},
                     ensure_ascii=False))


def cmd_shot(args):
    require_session("shot")
    path = getattr(args, "path", None) or SHOT_PATH
    try:
        ww, hh = capture_screen_bmp(path)
        print(json.dumps({"ok": True, "path": path, "width": ww, "height": hh},
                         ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": "shot_failed",
                          "detail": "%s: %s" % (type(e).__name__, e),
                          "path": path}, ensure_ascii=False))
        sys.exit(2)


def _point_from_args(args, nodes=None, windows=None):
    nx, ny = getattr(args, "nx", None), getattr(args, "ny", None)
    win = getattr(args, "win", None)
    if nx is not None and ny is not None and win is not None:
        if nodes is None or windows is None:
            _fail("normalized_point_needs_app", "nx/ny need app+tree context")
        wf = _win_frame_by_node_idx(windows, nodes, win)
        if not wf:
            _fail("window_frame_unavailable",
                  "no frame for window row %d; re-read the tree" % win)
        x0, y0, x1, y1 = wf
        ww, wh = x1 - x0, y1 - y0
        if ww <= 0 or wh <= 0:
            _fail("window_frame_unavailable", "degenerate window frame %s" % wf)
        return (x0 + float(nx) / 1000.0 * ww, y0 + float(ny) / 1000.0 * wh,
                "win%d:1000" % win)
    x, y = getattr(args, "x", None), getattr(args, "y", None)
    if x is None or y is None:
        _fail("missing_point",
              "give either app+win+nx+ny (0-1000) or x+y (absolute)")
    return float(x), float(y), "absolute"


def _win_frame_by_node_idx(windows, nodes, win_idx):
    for wi, _h, _t in windows:
        if wi == win_idx:
            if wi < len(nodes) and nodes[wi].frame:
                return nodes[wi].frame
            return None
    return None


def cmd_xy(args):
    """Click at a screen point. Reference-parity: app+win+nx+ny (0-1000) or
    absolute x+y. Re-resolves the window frame on every call."""
    require_session("xy")
    if getattr(args, "app", None) and getattr(args, "win", None) is not None:
        pid, name, exe, nodes, windows = _nodes_for(args)
        _remember(pid, nodes)
        x, y, how = _point_from_args(args, nodes, windows)
    else:
        x, y, how = _point_from_args(args)
    mouse_click_at(x, y)
    print(json.dumps({"ok": True, "method": "win:mouse", "at": how,
                      "x": round(x, 1), "y": round(y, 1)}, ensure_ascii=False))


def cmd_type(args):
    require_session("type")
    r = send_keys_text(args.text)
    print(json.dumps({"ok": r is True, "method": "win:WM_CHAR",
                      "chars": len(args.text or "")}, ensure_ascii=False))


def cmd_key(args):
    require_session("key")
    r = send_key_combo(args.combo)
    print(json.dumps({"ok": r is True, "method": "win:keybd",
                      "combo": args.combo,
                      "error": None if r is True else r}, ensure_ascii=False))


def cmd_scroll(args):
    require_session("scroll")
    direction = (args.direction or "down").lower()
    if direction not in ("up", "down"):
        _fail("bad_direction", "direction must be up or down")
    pages = float(args.pages or 1)
    lines = int(round(pages * 10))
    if direction == "down":
        lines = -lines
    if getattr(args, "app", None):
        pid, name, exe, nodes, windows = _nodes_for(args)
        if getattr(args, "idx", None) is not None:
            if args.idx >= len(nodes):
                _fail("index_out_of_range", "max_index=%d" % (len(nodes) - 1))
            _remember(pid, nodes)
            n = nodes[args.idx]
            c = centre_of(n.frame)
            if not c:
                _fail("no_frame", "idx %d has no frame" % args.idx)
            user32.SetForegroundWindow(n.hwnd)
            x, y, how = c[0], c[1], "element_centre"
        else:
            x, y, how = _point_from_args(args, nodes, windows)
    else:
        x, y, how = _point_from_args(args)
    # try native WM_VSCROLL on the control under the point
    mouse_wheel(x, y, lines)
    print(json.dumps({"ok": True, "method": "win:wheel", "at": how,
                      "x": round(x, 1), "y": round(y, 1),
                      "direction": direction, "lines": lines},
                     ensure_ascii=False))


def cmd_drag(args):
    require_session("drag")
    x1 = y1 = x2 = y2 = None
    how = None
    if getattr(args, "app", None) and getattr(args, "from_idx", None) is not None \
            and getattr(args, "to_idx", None) is not None:
        pid, name, exe, nodes, windows = _nodes_for(args)
        if args.from_idx >= len(nodes) or args.to_idx >= len(nodes):
            _fail("index_out_of_range", "max_index=%d" % (len(nodes) - 1))
        a, b = nodes[args.from_idx], nodes[args.to_idx]
        ca, cb = centre_of(a.frame), centre_of(b.frame)
        if not ca or not cb:
            _fail("no_frame", "both endpoints need a frame")
        x1, y1, x2, y2 = ca[0], ca[1], cb[0], cb[1]
        how = "element_centres"
    elif getattr(args, "win", None) is not None \
            and None not in (args.x, args.y, args.x2, args.y2):
        pid, name, exe, nodes, windows = _nodes_for(args)
        _remember(pid, nodes)
        wf = _win_frame_by_node_idx(windows, nodes, args.win)
        if not wf:
            _fail("window_frame_unavailable",
                  "no frame for window row %d" % args.win)
        x0, y0, x1_, y1_ = wf
        ww, wh = x1_ - x0, y1_ - y0
        x1 = x0 + float(args.x) / 1000.0 * ww
        y1 = y0 + float(args.y) / 1000.0 * wh
        x2 = x0 + float(args.x2) / 1000.0 * ww
        y2 = y0 + float(args.y2) / 1000.0 * wh
        how = "win%d:1000" % args.win
    elif None not in (args.x, args.y, args.x2, args.y2):
        x1, y1, x2, y2 = float(args.x), float(args.y), float(args.x2), float(args.y2)
        how = "absolute"
    else:
        _fail("missing_points",
              "give from_idx/to_idx, or win + x,y,x2,y2 (0-1000), or absolute")
    mouse_drag(x1, y1, x2, y2)
    print(json.dumps({"ok": True, "method": "win:mouse_drag", "at": how,
                      "from": [round(x1, 1), round(y1, 1)],
                      "to": [round(x2, 1), round(y2, 1)]}, ensure_ascii=False))


def cmd_seltext(args):
    """Select (or place caret at) text inside an Edit control, implemented
    over Win32 EM_SETSEL."""
    pid, name, exe, nodes, windows, n = _load_target(args, "seltext")
    if n.cls not in ("Edit", "RichEdit20W", "RICHEDIT50W"):
        _fail("not_editable", "idx %d is not an Edit control (cls=%s)"
              % (args.idx, n.cls))
    hwnd = n.hwnd
    # read current text
    L = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(L + 2)
    user32.SendMessageW(hwnd, WM_GETTEXT, L + 1, buf)
    text = buf.value or ""
    needle = args.text or ""
    if not needle:
        _fail("missing_text", "text to select is required")
    occ = int(getattr(args, "occurrence", None) or 1)
    prefix, suffix = getattr(args, "prefix", None), getattr(args, "suffix", None)
    if prefix or suffix:
        full = (prefix or "") + needle + (suffix or "")
        base = -1
        pos = -1
        for _ in range(max(1, occ)):
            base = text.find(full, base + 1)
            if base < 0:
                break
            pos = base
        if pos < 0:
            _fail("text_not_found", "not found %d times: %r" % (occ, full))
        loc = pos + len(prefix or "")
    else:
        pos = -1
        for _ in range(max(1, occ)):
            pos = text.find(needle, pos + 1)
            if pos < 0:
                break
        if pos < 0:
            _fail("text_not_found", "not found %d times: %r" % (occ, needle))
        loc = pos
    mode = (args.mode or "select").lower()
    if mode not in ("select", "before", "after"):
        _fail("bad_mode", "mode must be select, before, or after")
    length = len(needle) if mode == "select" else 0
    if mode == "after":
        loc += len(needle)
    # EM_SETSEL(start, end): start==end places the caret
    user32.SendMessageW(hwnd, EM_SETSEL, loc, loc + length)
    # read back selection
    start = ctypes.c_int()
    end = ctypes.c_int()
    user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
    verified = (start.value == loc and end.value == loc + length)
    print(json.dumps({"ok": True, "method": "win:EM_SETSEL", "mode": mode,
                      "loc": loc, "len": length, "selected_range": [start.value, end.value],
                      "verified": verified, "idx": args.idx, "app": name,
                      "pid": pid}, ensure_ascii=False))


def cmd_act(args):
    """Named action on a node. Windows parity set: Press (BM_CLICK),
    Toggle (for checkboxes via BM_CLICK), SetFocus, ScrollIntoView, etc."""
    pid, name, exe, nodes, windows, n = _load_target(args, "act")
    action = (args.name or "").lower()
    hwnd = n.hwnd
    if action in ("press", "click"):
        user32.SendMessageW(hwnd, BM_CLICK, 0, 0)
        print(json.dumps({"ok": True, "method": "win:BM_CLICK", "action": action,
                          "idx": args.idx, "app": name, "pid": pid},
                         ensure_ascii=False))
        return
    if action in ("setfocus", "focus"):
        user32.SetForegroundWindow(hwnd)
        print(json.dumps({"ok": True, "method": "win:SetForegroundWindow",
                          "action": action, "idx": args.idx}, ensure_ascii=False))
        return
    if action in ("show", "restore"):
        user32.ShowWindow(hwnd, SW_RESTORE)
        print(json.dumps({"ok": True, "method": "win:ShowWindow", "action": action,
                          "idx": args.idx}, ensure_ascii=False))
        return
    _fail("action_not_advertised",
          "action '%s' is not mapped; available: press, click, setfocus, "
          "show" % args.name)


def cmd_watch(args):
    """Continuous screenshot loop writing SHOT_PATH."""
    import threading
    iv = float(getattr(args, "interval", None) or 0.8)
    iv = max(0.2, min(iv, 10.0))
    if args.on:
        if not _WATCH["on"]:
            _WATCH.update(on=True, n=0, err=None)
            t = threading.Thread(target=_watch_loop, args=(iv,), daemon=True)
            t.start()
            _WATCH["thread"] = t
        _WATCH["interval"] = iv
    else:
        _WATCH["on"] = False
    print(json.dumps({"ok": True, "on": _WATCH["on"], "interval": iv,
                      "shots": _WATCH["n"], "path": SHOT_PATH,
                      "err": _WATCH["err"]}, ensure_ascii=False))


def _watch_loop(interval):
    while _WATCH["on"]:
        try:
            ww, hh = capture_screen_bmp(SHOT_PATH)
            _WATCH["n"] += 1
            _WATCH["ts"] = time.time()
        except Exception as e:
            _WATCH["err"] = "%s: %s" % (type(e).__name__, e)
        time.sleep(interval)


_WATCH = {"on": False, "n": 0, "ts": 0.0, "err": None, "thread": None}


def _fail(code, detail):
    print(json.dumps({"ok": False, "code": code, "error": code,
                      "detail": detail}, ensure_ascii=False))
    sys.exit(2)


# --------------------------------------------------------------------------
# Serve mode - the bridge across the session boundary
# --------------------------------------------------------------------------
TEMP = os.environ.get("TEMP") or os.environ.get("TMP") or "."
CMD_PATH = os.path.join(TEMP, "cu_cmd.jsonl")
STATUS_PATH = os.path.join(TEMP, "cu_status.json")
TREE_PATH = os.path.join(TEMP, "cu_tree.txt")
SHOT_PATH = os.path.join(TEMP, "cu_shot.bmp")
STOP_PATH = os.path.join(TEMP, "cu_stop")
ALIVE_PATH = os.path.join(TEMP, "cu_alive")

_NS_DEFAULTS = dict(app=None, idx=None, text=None, action=None, depth=12,
                    max_nodes=400, window=None, json=False, actions=False,
                    poll=0.2, wait=2.5, x=None, y=None, combo=None, path=None,
                    on=True, interval=0.8, name=None, direction=None, pages=None,
                    win=None, nx=None, ny=None,
                    from_idx=None, to_idx=None, x2=None, y2=None,
                    mode=None, prefix=None, suffix=None, occurrence=None,
                    force=False)


def _dispatch(req):
    import io
    import contextlib
    import traceback
    from types import SimpleNamespace
    name = req.get("cmd")
    table = {"probe": cmd_probe, "apps": cmd_apps, "tree": cmd_tree,
             "click": cmd_click, "set": cmd_set, "focus": cmd_focus,
             "info": cmd_info, "launch": cmd_launch, "shot": cmd_shot,
             "xy": cmd_xy, "type": cmd_type, "key": cmd_key,
             "watch": cmd_watch, "activate": cmd_activate,
             "act": cmd_act, "scroll": cmd_scroll, "drag": cmd_drag,
             "seltext": cmd_seltext}
    fn = table.get(name)
    if not fn:
        return 2, "unknown cmd: %s" % name
    ns = dict(_NS_DEFAULTS)
    for k, v in req.items():
        if k != "cmd":
            ns[k] = v
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            fn(SimpleNamespace(**ns))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception:
        code = 1
        buf.write(traceback.format_exc())
    return code, buf.getvalue()


def cmd_serve(args):
    import time as _t
    for p in (CMD_PATH, STATUS_PATH, TREE_PATH, STOP_PATH):
        try:
            os.remove(p)
        except OSError:
            pass
    open(CMD_PATH, "a").close()

    check_session()
    ok = _SESSION["ok"]
    banner = [
        "cu_ui serve ready (Windows)",
        "  session : %s" % ok,
        "  station : %s" % _SESSION.get("station"),
        "  python  : %s" % sys.executable,
        "  cmd     : %s   (append one JSON per line)" % CMD_PATH,
        "  status  : %s" % STATUS_PATH,
        "  tree    : %s" % TREE_PATH,
        "  shot    : %s" % SHOT_PATH,
        "  alive   : %s" % ALIVE_PATH,
        "  stop    : touch %s" % STOP_PATH,
    ]
    if not ok:
        banner.append("")
        banner.append(_SESSION.get("detail", "NO_GUI_SESSION"))
    print("\n".join(banner), flush=True)

    try:
        with open(STATUS_PATH, "w") as sf:
            json.dump({"id": 0, "cmd": "__startup__", "ok": ok,
                       "exit": 0 if ok else 3, "session": ok,
                       "station": _SESSION.get("station"), "pid": os.getpid(),
                       "python": sys.executable,
                       "started_at": _t.strftime("%Y-%m-%d %H:%M:%S")},
                      sf, ensure_ascii=False, indent=2)
    except OSError:
        pass

    seen = 0
    last_beat = 0.0
    while True:
        if os.path.exists(STOP_PATH):
            break
        now = _t.time()
        if now - last_beat >= 1.0:
            last_beat = now
            try:
                with open(ALIVE_PATH, "w") as af:
                    af.write("%d %s\n" % (os.getpid(), ok))
            except OSError:
                pass
        try:
            with open(CMD_PATH, "r") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        while seen < len(lines):
            raw = lines[seen]
            seen += 1
            if not raw.strip():
                continue
            try:
                req = json.loads(raw)
            except Exception as e:
                st = {"ok": False, "error": "bad_json", "detail": str(e),
                      "raw": raw[:200]}
            else:
                code, out = _dispatch(req)
                st = {"id": req.get("id"), "cmd": req.get("cmd"),
                      "exit": code, "ok": code == 0}
                if req.get("cmd") == "tree" and not req.get("json"):
                    with open(TREE_PATH, "w") as tf:
                        tf.write(out)
                    st["tree_file"] = TREE_PATH
                    st["lines"] = out.count("\n") + 1
                    st["preview"] = out[:400]
                else:
                    st["out"] = out[:8000]
            with open(STATUS_PATH, "w") as sf:
                json.dump(st, sf, ensure_ascii=False, indent=2)
        _t.sleep(args.poll if getattr(args, "poll", None) else 0.2)
    print("serve stopped")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(prog="cu_ui.py",
                                description="Windows UI engine for computer-use")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("probe").set_defaults(fn=cmd_probe)
    sub.add_parser("apps").set_defaults(fn=cmd_apps)
    sv = sub.add_parser("serve", help="poll %TEMP%/cu_cmd.jsonl (run in your session)")
    sv.add_argument("--poll", type=float, default=0.2)
    sv.set_defaults(fn=cmd_serve)

    t = sub.add_parser("tree")
    t.add_argument("app")
    t.add_argument("--depth", type=int, default=12)
    t.add_argument("--max-nodes", type=int, default=400)
    t.add_argument("--window", type=int, default=None)
    t.add_argument("--actions", action="store_true")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_tree)

    c = sub.add_parser("click")
    c.add_argument("app")
    c.add_argument("idx", type=int)
    c.add_argument("--force", action="store_true")
    c.add_argument("--depth", type=int, default=12)
    c.add_argument("--max-nodes", type=int, default=400)
    c.set_defaults(fn=cmd_click)

    s = sub.add_parser("set")
    s.add_argument("app")
    s.add_argument("idx", type=int)
    s.add_argument("text")
    s.add_argument("--force", action="store_true")
    s.add_argument("--depth", type=int, default=12)
    s.add_argument("--max-nodes", type=int, default=400)
    s.set_defaults(fn=cmd_set)

    l = sub.add_parser("launch")
    l.add_argument("app")
    l.add_argument("--wait", type=float, default=2.5)
    l.set_defaults(fn=cmd_launch)

    f = sub.add_parser("focus")
    f.add_argument("app")
    f.set_defaults(fn=cmd_focus)

    i = sub.add_parser("info")
    i.add_argument("app")
    i.add_argument("idx", type=int)
    i.add_argument("--depth", type=int, default=12)
    i.add_argument("--max-nodes", type=int, default=400)
    i.set_defaults(fn=cmd_info)

    sh = sub.add_parser("shot")
    sh.add_argument("--path", default=None)
    sh.set_defaults(fn=cmd_shot)

    xy = sub.add_parser("xy")
    xy.add_argument("x", type=float, nargs="?", default=None)
    xy.add_argument("y", type=float, nargs="?", default=None)
    xy.add_argument("--app", default=None)
    xy.add_argument("--win", type=int, default=None)
    xy.add_argument("--nx", type=float, default=None)
    xy.add_argument("--ny", type=float, default=None)
    xy.add_argument("--depth", type=int, default=12)
    xy.add_argument("--max-nodes", type=int, default=400)
    xy.set_defaults(fn=cmd_xy)

    t2 = sub.add_parser("type")
    t2.add_argument("text")
    t2.set_defaults(fn=cmd_type)

    k = sub.add_parser("key")
    k.add_argument("combo")
    k.set_defaults(fn=cmd_key)

    w = sub.add_parser("watch")
    w.add_argument("--on", dest="on", action="store_true", default=True)
    w.add_argument("--off", dest="on", action="store_false")
    w.add_argument("--interval", type=float, default=0.8)
    w.set_defaults(fn=cmd_watch)

    a2 = sub.add_parser("activate")
    a2.add_argument("app")
    a2.set_defaults(fn=cmd_activate)

    act = sub.add_parser("act")
    act.add_argument("app")
    act.add_argument("idx", type=int)
    act.add_argument("name")
    act.add_argument("--force", action="store_true")
    act.add_argument("--depth", type=int, default=12)
    act.add_argument("--max-nodes", type=int, default=400)
    act.set_defaults(fn=cmd_act)

    sc = sub.add_parser("scroll")
    sc.add_argument("direction", nargs="?", default=None)
    sc.add_argument("--app", default=None)
    sc.add_argument("--idx", type=int, default=None)
    sc.add_argument("--pages", type=float, default=1.0)
    sc.add_argument("--win", type=int, default=None)
    sc.add_argument("--nx", type=float, default=None)
    sc.add_argument("--ny", type=float, default=None)
    sc.add_argument("--x", type=float, default=None)
    sc.add_argument("--y", type=float, default=None)
    sc.add_argument("--force", action="store_true")
    sc.add_argument("--depth", type=int, default=12)
    sc.add_argument("--max-nodes", type=int, default=400)
    sc.set_defaults(fn=cmd_scroll)

    dr = sub.add_parser("drag")
    dr.add_argument("x", type=float, nargs="?", default=None)
    dr.add_argument("y", type=float, nargs="?", default=None)
    dr.add_argument("x2", type=float, nargs="?", default=None)
    dr.add_argument("y2", type=float, nargs="?", default=None)
    dr.add_argument("--app", default=None)
    dr.add_argument("--from-idx", dest="from_idx", type=int, default=None)
    dr.add_argument("--to-idx", dest="to_idx", type=int, default=None)
    dr.add_argument("--win", type=int, default=None)
    dr.add_argument("--nx", type=float, default=None)
    dr.add_argument("--ny", type=float, default=None)
    dr.add_argument("--depth", type=int, default=12)
    dr.add_argument("--max-nodes", type=int, default=400)
    dr.set_defaults(fn=cmd_drag)

    st = sub.add_parser("seltext")
    st.add_argument("app")
    st.add_argument("idx", type=int)
    st.add_argument("text")
    st.add_argument("--mode", default="select", choices=["select", "before", "after"])
    st.add_argument("--prefix", default=None)
    st.add_argument("--suffix", default=None)
    st.add_argument("--occurrence", type=int, default=1)
    st.add_argument("--force", action="store_true")
    st.add_argument("--depth", type=int, default=12)
    st.add_argument("--max-nodes", type=int, default=400)
    st.set_defaults(fn=cmd_seltext)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        sys.exit(1)
    args.fn(args)


if __name__ == "__main__":
    main()
