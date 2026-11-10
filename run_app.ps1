# He-3 脉冲信号模拟与零功率反应堆数字孪生系统 启动脚本
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  He-3 脉冲信号模拟与零功率反应堆数字孪生系统" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "系统中未找到 Python 命令，请确认已安装 Python 3.11+ 并将其添加到系统 PATH。"
    pause
    exit 1
}

$env:PYTHONPATH = "src;$PWD"
Write-Host "[OK] 环境配置完成 (PYTHONPATH=src;$PWD)" -ForegroundColor Gray
Write-Host "正在启动 Streamlit Web 交互系统..." -ForegroundColor Yellow
Write-Host "本地服务地址: http://127.0.0.1:8501" -ForegroundColor Green
Write-Host "提示: 终端按下 Ctrl + C 可终止服务。" -ForegroundColor DarkGray

python -m streamlit run src/he3sim/ui/app.py --server.address 127.0.0.1 --server.port 8501
