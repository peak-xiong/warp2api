@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM warp2api Windows 停止脚本
REM 停止所有相关的服务器进程

REM Windows CMD 不支持ANSI颜色，移除颜色定义以保持与Mac脚本一致的逻辑

REM 从 .env 文件加载环境变量（如果存在）
if exist ".env" (
    for /f "tokens=*" %%i in (.env) do (
        set "%%i"
    )
)

REM 环境变量控制日志输出，默认不打印日志
REM 设置 W2A_VERBOSE=true 来启用详细日志输出
if "%W2A_VERBOSE%"=="" set "W2A_VERBOSE=false"

REM 日志函数
:log_info
if "%W2A_VERBOSE%"=="true" (
    echo [%DATE% %TIME%] INFO: %~1
)
goto :eof

:log_success
if "%W2A_VERBOSE%"=="true" (
    echo [%DATE% %TIME%] SUCCESS: %~1
)
goto :eof

:log_warning
if "%W2A_VERBOSE%"=="true" (
    echo [%DATE% %TIME%] WARNING: %~1
)
goto :eof

:log_error
echo [%DATE% %TIME%] ERROR: %~1
goto :eof

REM 显示当前状态
:show_status
echo.
echo ============================================
echo 📊 当前服务器状态
echo ============================================

REM 检查端口28888
netstat -an | find "28888" >nul 2>&1
if %errorlevel%==0 (
    echo ✅ Protobuf桥接服务器 (端口28888): 运行中
) else (
    echo ❌ Protobuf桥接服务器 (端口28888): 已停止
)

REM 检查端口28889
netstat -an | find "28889" >nul 2>&1
if %errorlevel%==0 (
    echo ✅ OpenAI兼容API服务器 (端口28889): 运行中
) else (
    echo ❌ OpenAI兼容API服务器 (端口28889): 已停止
)

echo ============================================
goto :eof

REM 停止服务器函数
:stop_servers
call :log_info "正在停止warp2api服务器..."

REM 首先尝试通过进程名停止我们的Python进程
call :log_info "终止Python服务器进程..."
for /f "tokens=2" %%a in ('tasklist /FI "IMAGENAME eq python.exe" /FO CSV ^| find "python.exe"') do (
    REM 检查进程命令行是否包含我们的脚本
    for /f "tokens=*" %%c in ('wmic process where "ProcessId=%%a" get CommandLine /value 2^>nul ^| find "warp2api-bridge"') do (
        call :log_info "终止Protobuf桥接服务器进程 (PID: %%a)"
        taskkill /PID %%a /F >nul 2>&1
    )
    for /f "tokens=*" %%c in ('wmic process where "ProcessId=%%a" get CommandLine /value 2^>nul ^| find "warp2api-openai"') do (
        call :log_info "终止OpenAI兼容API服务器进程 (PID: %%a)"
        taskkill /PID %%a /F >nul 2>&1
    )
)

REM 停止端口相关的进程（作为备用方法）
call :log_info "清理端口进程..."
for /f "tokens=5" %%a in ('netstat -ano ^| find "28888"') do (
    REM 检查是否是我们自己的进程
    for /f "tokens=*" %%c in ('wmic process where "ProcessId=%%a" get CommandLine /value 2^>nul') do (
        echo %%c | findstr /C:"warp2api-bridge" >nul
        if !errorlevel!==0 (
            call :log_info "终止端口28888的服务器进程 (PID: %%a)"
            taskkill /PID %%a /F >nul 2>&1
        )
    )
)
for /f "tokens=5" %%a in ('netstat -ano ^| find "28889"') do (
    REM 检查是否是我们自己的进程
    for /f "tokens=*" %%c in ('wmic process where "ProcessId=%%a" get CommandLine /value 2^>nul') do (
        echo %%c | findstr /C:"warp2api-openai" >nul
        if !errorlevel!==0 (
            call :log_info "终止端口28889的服务器进程 (PID: %%a)"
            taskkill /PID %%a /F >nul 2>&1
        )
    )
)

REM 等待进程完全停止
timeout /t 2 >nul

REM 验证停止状态
netstat -an | find "28888" >nul 2>&1
set PORT_28888_RUNNING=%errorlevel%
netstat -an | find "28889" >nul 2>&1
set PORT_28889_RUNNING=%errorlevel%

if %PORT_28888_RUNNING%==1 if %PORT_28889_RUNNING%==1 (
    call :log_success "所有服务器已成功停止"
) else (
    call :log_warning "某些进程可能仍在运行，请手动检查"
)

REM 清理日志文件（自动清理，与Mac脚本保持一致）
del *.log 2>nul
call :log_info "日志文件已清理"
goto :eof

REM 显示帮助信息
:show_help
echo warp2api Windows 停止脚本
echo.
echo 用法:
echo   stop.bat          # 停止所有服务器
echo   stop.bat status   # 查看服务器状态
echo   stop.bat help     # 显示此帮助信息
echo.
echo 功能:
echo   - 安全停止所有warp2api相关进程
echo   - 清理端口占用
echo   - 可选清理日志文件
echo   - 显示详细的状态信息
goto :eof

REM 主函数
:main
if "%1"=="status" (
    call :show_status
) else if "%1"=="help" (
    call :show_help
) else if "%1"=="-h" (
    call :show_help
) else if "%1"=="--help" (
    call :show_help
) else if "%1"=="" (
    call :show_status
    call :stop_servers
) else (
    call :log_error "未知参数: %1"
    echo.
    call :show_help
    exit /b 1
)
goto :eof

REM 执行主函数
call :main %*
