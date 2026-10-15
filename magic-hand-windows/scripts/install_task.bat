@echo off
REM ============================================================
REM  注册「登录时自动启动 CU 桥接」的计划任务。
REM ============================================================
REM  Windows 端必须「仅当用户登录时运行」(/IT == InteractiveToken)，
REM  否则任务会跑在 session 0 非交互会话里，拿不到桌面（NO_GUI_SESSION）。
REM
REM  偏好手动启动？直接双击 scripts\start_cu_bridge.bat 即可，不必装任务。
REM ============================================================

setlocal EnableDelayedExpansion
set "SKILL_DIR=%~dp0"
if "%SKILL_DIR:~-1%"=="\" set "SKILL_DIR=%SKILL_DIR:~0,-1%"

REM --- 定位 Python ---
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

echo %PY% | findstr /i /c:":" >nul
if not errorlevel 1 (
  if not exist "%PY%" goto :nopy
)

echo 注册任务 "WorkBuddy CU Bridge" ...
echo   解释器: %PY%
echo   脚本  : %SKILL_DIR%\cu_ui.py
echo.

schtasks /Create /TN "WorkBuddy CU Bridge" ^
 /TR "\"%PY%\" \"%SKILL_DIR%\cu_ui.py\" serve" ^
 /SC ONLOGON /IT /F

if errorlevel 1 (
  echo.
  echo [ERROR] 注册失败。常见原因：需要管理员/本地策略限制，或 %TEMP% 不可写。
  echo         也可以直接用「任务计划程序」导入 templates\ 下的 XML 模板。
  goto :done
)

echo.
echo [OK] 已创建任务 "WorkBuddy CU Bridge"，下次登录时自动启动桥接。
echo      管理：任务计划程序 -^> 任务计划程序库 -^> WorkBuddy CU Bridge
echo      停止：schtasks /End    /TN "WorkBuddy CU Bridge"
echo      删除：schtasks /Delete /TN "WorkBuddy CU Bridge" /F
goto :done

:nopy
echo [ERROR] 找不到可用的 Python。请安装 Python 3.8+ 并确保 py / python 在 PATH 里。

:done
echo.
pause
