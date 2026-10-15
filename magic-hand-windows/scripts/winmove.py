#!/usr/bin/env python3
"""winmove.py - move / resize / maximize a top-level window on Windows.

Pure ctypes (no third-party deps). Companion to cu_ui.py: cu_ui.py can click
and screenshot but cannot reposition a window; self-drawn apps (WeChat etc.)
sometimes grow past the screen edge, and you need to pull them back.

Usage:
  python winmove.py --list <exe-or-name>                 # list windows: idx, title, rect
  python winmove.py <exe-or-name> --rect X Y W H         # move+resize (pixels, screen space)
  python winmove.py <exe-or-name> --max                  # maximize
  python winmove.py <exe-or-name> --restore              # restore (un-maximize)
  python winmove.py <exe-or-name> --title SUBSTR ...     # pick window whose title contains SUBSTR

<exe-or-name> matches case-insensitively against the process exe basename
(without .exe) or the window title.
"""
import ctypes
import json
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def list_processes():
    """Return list of (pid, exe_basename_lower_noext)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    out = []
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            exe = entry.szExeFile.decode("mbcs", "replace")
            base = exe[:-4] if exe.lower().endswith(".exe") else exe
            out.append((int(entry.th32ProcessID), base.lower()))
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return out


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, ctypes.c_int, wintypes.BOOL]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def enum_windows():
    """Return list of dicts for visible top-level windows."""
    items = []

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd):
            return True
        ln = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(ln + 2)
        user32.GetWindowTextW(hwnd, buf, ln + 2)
        title = buf.value
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        items.append({
            "hwnd": int(hwnd), "pid": int(pid.value), "title": title,
            "rect": [r.left, r.top, r.right, r.bottom],
        })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return items


def match(target, title_filter=None):
    target = target.lower()
    procs = {pid: name for pid, name in list_processes()}
    wins = enum_windows()
    hits = []
    for w in wins:
        exe = procs.get(w["pid"], "")
        ok_exe = (exe == target) or (exe and target in exe)
        ok_title = bool(w["title"]) and (target in w["title"].lower())
        if not (ok_exe or ok_title):
            continue
        if title_filter and title_filter.lower() not in w["title"].lower():
            continue
        hits.append(w)
    return hits


def pick(hits):
    """Pick the largest window (by area); ties broken by later order."""
    if not hits:
        return None
    def area(w):
        x0, y0, x1, y1 = w["rect"]
        return max(0, x1 - x0) * max(0, y1 - y0)
    return sorted(hits, key=area)[-1]


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    list_mode = False
    title_filter = None
    rect = None
    do_max = do_restore = False
    target = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--list":
            list_mode = True
        elif a == "--rect":
            rect = [int(x) for x in args[i + 1:i + 5]]
            i += 4
        elif a == "--max":
            do_max = True
        elif a == "--restore":
            do_restore = True
        elif a == "--title":
            title_filter = args[i + 1]
            i += 1
        elif target is None:
            target = a
        i += 1

    if target is None:
        print(json.dumps({"ok": False, "error": "no_target"}, ensure_ascii=False))
        return 2

    hits = match(target, title_filter)
    if list_mode:
        print(json.dumps({"ok": True, "target": target, "count": len(hits),
                          "windows": [{"hwnd": h["hwnd"], "pid": h["pid"],
                                       "title": h["title"], "rect": h["rect"]}
                                      for h in hits]},
                         ensure_ascii=False))
        return 0

    w = pick(hits)
    if not w:
        print(json.dumps({"ok": False, "error": "window_not_found",
                          "target": target}, ensure_ascii=False))
        return 2

    hwnd = w["hwnd"]
    if rect:
        x, y, ww, hh = rect
        ok = user32.MoveWindow(hwnd, x, y, ww, hh, True)
        act = "move"
    elif do_max:
        ok = user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        act = "maximize"
    elif do_restore:
        ok = user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        act = "restore"
    else:
        print(json.dumps({"ok": False, "error": "no_action"},
                         ensure_ascii=False))
        return 2

    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    print(json.dumps({"ok": bool(ok), "action": act, "hwnd": hwnd,
                      "title": w["title"],
                      "rect": [r.left, r.top, r.right, r.bottom]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
