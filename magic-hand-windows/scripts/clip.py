#!/usr/bin/env python3
"""clip.py - read / write the Windows clipboard as text (pure ctypes).

Companion to cu_ui.py. Scraping self-drawn apps often goes through the
clipboard: copy in the app (Ctrl+C / a "copy link" menu), then read it here;
or set text here, then paste into another app (Ctrl+V / a "paste" menu).

Usage:
  python clip.py get                 # print clipboard text to stdout
  python clip.py set "some text"     # put text on the clipboard
  python clip.py set --file P.txt    # put the contents of a UTF-8 file on it
  python clip.py clear               # empty the clipboard
"""
import ctypes
import sys
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.CloseClipboard.argtypes = []
user32.EmptyClipboard.argtypes = []
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HANDLE
kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
kernel32.GlobalFree.argtypes = [wintypes.HANDLE]


def get_text():
    if not user32.OpenClipboard(None):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_text(text):
    data = text.encode("utf-16-le") + b"\x00\x00"
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    p = kernel32.GlobalLock(h)
    if not p:
        kernel32.GlobalFree(h)
        return False
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            return False
    finally:
        user32.CloseClipboard()
    return True


def clear():
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        return True
    finally:
        user32.CloseClipboard()


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = args[0]
    if cmd == "get":
        t = get_text()
        if t is None:
            print("(empty clipboard)")
            return 0
        sys.stdout.write(t)
        if not t.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    if cmd == "set":
        rest = args[1:]
        if rest and rest[0] == "--file":
            with open(rest[1], "r", encoding="utf-8") as f:
                text = f.read()
        else:
            text = " ".join(rest)
        ok = set_text(text)
        print("ok" if ok else "failed", len(text))
        return 0 if ok else 2
    if cmd == "clear":
        print("ok" if clear() else "failed")
        return 0
    print("unknown command: %s" % cmd)
    return 2


if __name__ == "__main__":
    sys.exit(main())
