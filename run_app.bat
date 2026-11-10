@echo off
chcp 65001 >nul
title He-3 脉冲信号与零功率反应堆数字孪生系统
echo ================================================================
echo   He-3 脉冲信号模拟与零功率反应堆数字孪生系统
echo ================================================================
echo.
echo [1/3] 正在检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 系统中未找到 Python 命令！
    echo 请确认已安装 Python 3.11+ 并勾选 "Add Python to PATH"。
    echo.
    pause
    exit /b 1
)

echo [2/3] 设置运行环境 (PYTHONPATH)...
set PYTHONPATH=src;%CD%

echo [3/3] 正在启动 Streamlit Web 交互界面...
echo 本地访问地址: http://127.0.0.1:8501
echo 正在打开默认浏览器，请稍候...
echo ================================================================
echo 提示: 如需停止运行，请在本窗口按下 Ctrl + C。
echo.

python -m streamlit run src/he3sim/ui/app.py --server.address 127.0.0.1 --server.port 8501

pause
