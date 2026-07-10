<#
.SYNOPSIS
    KG 平台一键重启脚本
.DESCRIPTION
    重启顺序：Docker 容器 -> 后端 FastAPI -> 前端 Vite
    端口：PostgreSQL 5432 | Neo4j 7474/7687 | 后端 8000 | 前端 5173
.NOTES
    需以普通用户权限运行（机器级 PATH 修改需管理员）
#>

# ============ 配置 ============
$ProjectRoot   = "C:\Users\11491\Desktop\KG\kg-platform"
$BackendDir    = "$ProjectRoot\backend"
$FrontendDir   = "$ProjectRoot\frontend"
$PythonExe     = "C:\Users\11491\AppData\Local\Programs\Python\Python310\python.exe"
$CuDnnBin      = "C:\Users\11491\Downloads\cudnn_cuda11\cudnn-windows-x86_64-8.9.7.29_cuda11-archive\bin"
$BackendLog    = "$BackendDir\uvicorn.log"
$BackendErrLog = "$BackendDir\uvicorn.err.log"
$FrontendLog   = "$FrontendDir\vite.log"
$FrontendErrLog= "$FrontendDir\vite.err.log"

# ============ 函数 ============
function Stop-ProcessByName {
    param([string]$Name, [string[]]$ExcludePaths)
    $procs = Get-Process -Name $Name -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($ExcludePaths -and $p.Path -and ($ExcludePaths | Where-Object { $p.Path -like $_ })) {
            Write-Host "  [skip] $Name PID=$($p.Id) ($($p.Path))" -ForegroundColor DarkGray
            continue
        }
        Write-Host "  [kill] $Name PID=$($p.Id)" -ForegroundColor Yellow
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    }
}

function Wait-Port {
    param([int]$Port, [int]$TimeoutSec = 30)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -WarningAction SilentlyContinue
        if ($r.TcpTestSucceeded) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# ============ 1. 停止现有进程 ============
Write-Host ""
Write-Host "[1/5] Stopping processes..." -ForegroundColor Cyan
Stop-ProcessByName -Name "python" -ExcludePaths @("*\networkd*", "*\nvidia*")
Stop-ProcessByName -Name "node" -ExcludePaths @("*\QClaw*", "*\.qclaw*", "*\openclaw*")
Start-Sleep -Seconds 2

# ============ 2. Docker 容器 ============
Write-Host ""
Write-Host "[2/5] Docker containers..." -ForegroundColor Cyan

$dockerRunning = $false
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerRunning = $true }
} catch {}

if (-not $dockerRunning) {
    Write-Host "  Starting Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt 120) {
        try { docker info 2>&1 | Out-Null; if ($LASTEXITCODE -eq 0) { break } } catch {}
        Start-Sleep -Seconds 3
    }
}

Write-Host "  Restarting kg-postgres and kg-neo4j..." -ForegroundColor Yellow
docker restart kg-postgres kg-neo4j 2>&1 | Out-Null

if (Wait-Port -Port 5432 -TimeoutSec 30) {
    Write-Host "  [OK] PostgreSQL 5432" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] PostgreSQL 5432 not ready" -ForegroundColor Red
}

if (Wait-Port -Port 7474 -TimeoutSec 30) {
    Write-Host "  [OK] Neo4j 7474" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Neo4j 7474 not ready" -ForegroundColor Red
}

# ============ 3. 启动后端 ============
Write-Host ""
Write-Host "[3/5] Starting backend FastAPI (8000)..." -ForegroundColor Cyan

$env:Path = $env:Path + ";" + $CuDnnBin

Set-Location $BackendDir
Start-Process -FilePath $PythonExe `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $BackendLog `
    -RedirectStandardError $BackendErrLog

if (Wait-Port -Port 8000 -TimeoutSec 30) {
    Write-Host "  [OK] Backend 8000" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Backend 8000 failed, check: $BackendLog" -ForegroundColor Red
}

# ============ 4. 启动前端 ============
Write-Host ""
Write-Host "[4/5] Starting frontend Vite (5173)..." -ForegroundColor Cyan

Set-Location $FrontendDir
$viteCmd = "$FrontendDir\node_modules\.bin\vite.cmd"
Start-Process -FilePath $viteCmd `
    -ArgumentList "--host" `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $FrontendLog `
    -RedirectStandardError $FrontendErrLog

if (Wait-Port -Port 5173 -TimeoutSec 30) {
    Write-Host "  [OK] Frontend 5173" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Frontend 5173 failed, check: $FrontendLog" -ForegroundColor Red
}

# ============ 5. 汇总 ============
Write-Host ""
Write-Host "[5/5] Service Status" -ForegroundColor Cyan
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  Backend:   http://localhost:8000/docs"
Write-Host "  Neo4j:     http://localhost:7474"
Write-Host "  PostgreSQL: localhost:5432"
Write-Host ""

$ports = [ordered]@{
    "PostgreSQL" = 5432
    "Neo4j"      = 7474
    "Backend"    = 8000
    "Frontend"   = 5173
}
foreach ($k in $ports.Keys) {
    $r = Test-NetConnection -ComputerName 127.0.0.1 -Port $ports[$k] -WarningAction SilentlyContinue
    if ($r.TcpTestSucceeded) {
        Write-Host "  [OK]   $k ($($ports[$k]))" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $k ($($ports[$k]))" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Restart complete." -ForegroundColor Cyan
Write-Host ""
