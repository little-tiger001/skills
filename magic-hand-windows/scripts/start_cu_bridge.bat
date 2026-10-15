@echo off
REM ============================================================
REM  CU 桥接启动器  (magic-hand / 妙控手 Windows 版)
REM  双击本文件即可在「你自己的交互式用户会话」里启动 serve。
REM ============================================================
REM  为什么必须走这个桥：
REM    WorkBuddy 的 Bash 子进程可能不在交互式桌面会话(WinSta0)里，
REM    此时它能读到自己的（通常为空的）窗口列表，却无法移动鼠标、
REM    无法向真实窗口发送按键 —— 命令返回成功但桌面毫无反应。
REM    由你双击本文件启动的进程继承你的交互式会话，因此能真正操控桌面。
REM
REM  通信协议（%TEMP% 下文件）：
REM    %TEMP%\cu_cmd.jsonl    agent 追加一行 JSON 指令
REM    %TEMP%\cu_status.json  serve 回写最近一条指令的结果
REM    %TEMP%\cu_tree.txt     tree 命令的完整输出
REM    %TEMP%\cu_shot.bmp     最近一次截图
REM  停止：在别处执行   echo. > "%TEMP%\cu_stop"   或直接关闭本窗口。
REM ============================================================

setlocal EnableDelayedExpansion
set "SKILL_DIR=%~dp0"
if "%SKILL_DIR:~-1%"=="\" set "SKILL_DIR=%SKILL_DIR:~0,-1%"

REM --- 定位 Python：纯 ctypes 引擎，任意 Windows Python 3.8+ 均可 ---
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY ( where python3 >nul 2>&1 && set "PY=python3" )
if not defined PY (
  rem WorkBuddy 托管运行时（若安装了的话）
  for /d %%v in ("%USERPROFILE%\.workbuddy\binaries\python\versions\*") do (
    set "PY=%%v\python.exe"
  )
)
if not defined PY goto :nopy

rem 若 PY 是完整路径（含盘符），确认它真的存在
echo %PY% | findstr /i /c:":" >nul
if not errorlevel 1 (
  if not exist "%PY%" goto :nopy
)

echo ==============================================
echo   CU 桥接  (magic-hand / Windows)
echo ==============================================
echo   使用解释器: %PY%
echo.

del /q "%TEMP%\cu_stop" 2>nul

"%PY%" "%SKILL_DIR%\cu_ui.py" probe
if errorlevel 1 (
  echo.
  echo [!] 探测未就绪（verdict != READY）。最常见原因：当前进程不在交互式
  echo     桌面会话(WinSta0)。请「双击本文件」或「任务计划程序 At logon」启动，
  echo     不要从服务的非交互会话里拉起。
  echo.
)

echo.
echo ^>^>^> 启动 serve。保持本窗口开着，回到 WorkBuddy 继续下指令。
echo     停止：在别处执行   echo. ^> "%TEMP%\cu_stop"   或直接关闭本窗口。
echo ==============================================
echo.

"%PY%" "%SKILL_DIR%\cu_ui.py" serve
goto :eof

:nopy
echo [ERROR] 找不到可用的 Python。
echo         请安装 Python 3.8+ 并确保 py / python 在 PATH 里，或改用
echo         scripts\install_task.bat 说明的方式手动指定解释器。
pause
exit /b 1
