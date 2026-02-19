@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM warp2api Windows 快速启动脚本
REM 启动两个服务器：Protobuf桥接服务器和多协议网关服务器

REM Windows CMD 不支持ANSI颜色，移除颜色定义以保持与Mac脚本一致的逻辑

REM 自动配置环境变量
:auto_configure
call :log_info "自动配置环境变量..."

REM 如果 .env 不存在，从 .env.example 复制
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        call :log_success "已从 .env.example 复制配置到 .env"
    ) else (
        call :log_warning ".env.example 文件不存在，跳过配置复制"
    )
)

REM 检查并生成 API_TOKEN
if exist ".env" (
    REM 获取当前API_TOKEN值
    set "CURRENT_API_TOKEN="
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="API_TOKEN" (
            set "CURRENT_API_TOKEN=%%b"
            set "CURRENT_API_TOKEN=!CURRENT_API_TOKEN:"=!"
        )
    )

    REM 如果API_TOKEN不存在或为默认值001，则设置为固定值0000
    if "!CURRENT_API_TOKEN!"=="" (
        set "API_TOKEN=0000"
        echo API_TOKEN=!API_TOKEN!>> ".env"
        call :log_success "已设置固定API_TOKEN: !API_TOKEN!"
    ) else if "!CURRENT_API_TOKEN!"=="001" (
        set "API_TOKEN=0000"
        REM 替换API_TOKEN行
        (for /f "tokens=*" %%i in (.env) do (
            set "line=%%i"
            echo !line! | findstr "^API_TOKEN=" >nul
            if !errorlevel!==0 (
                echo API_TOKEN=!API_TOKEN!
            ) else (
                echo !line!
            )
        )) > ".env.tmp"
        move ".env.tmp" ".env" >nul
        call :log_success "已设置固定API_TOKEN: !API_TOKEN!"
    ) else (
        call :log_info "API_TOKEN 已存在且非默认值，跳过设置"
    )

    REM 设置日志开关为默认状态（静默模式）
    set "VERBOSE_FOUND="
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="W2A_VERBOSE" (
            set "VERBOSE_FOUND=1"
        )
    )
    if not defined VERBOSE_FOUND (
        echo W2A_VERBOSE=false>> ".env"
        call :log_success "已设置日志输出为静默模式"
    )
)
goto :eof

REM 设置代理排除列表，避免本地服务被代理干扰
if "%NO_PROXY%"=="" set "NO_PROXY=127.0.0.1,localhost"

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

REM 检查Python版本
:check_python
call :log_info "检查Python版本..."
python --version >nul 2>&1
if errorlevel 1 (
    call :log_error "未找到Python，请确保Python 3.9+已安装"
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
call :log_info "Python版本: %PYTHON_VERSION%"

REM 检查Python版本号
for /f "tokens=2 delims=." %%a in ("%PYTHON_VERSION%") do set PYTHON_MAJOR=%%a
for /f "tokens=3 delims=." %%a in ("%PYTHON_VERSION%") do set PYTHON_MINOR=%%a

if %PYTHON_MAJOR% lss 3 (
    call :log_warning "推荐使用Python 3.13+，但当前版本 %PYTHON_VERSION% 仍可工作"
) else if %PYTHON_MAJOR%==3 if %PYTHON_MINOR% lss 9 (
    call :log_warning "推荐使用Python 3.13+，但当前版本 %PYTHON_VERSION% 仍可工作"
)
goto :eof

REM 检查依赖
:check_dependencies
call :log_info "检查项目依赖..."

set PACKAGES=fastapi uvicorn httpx protobuf websockets openai
set MISSING_PACKAGES=

for %%p in (%PACKAGES%) do (
    python -c "import %%p" >nul 2>&1
    if errorlevel 1 (
        set MISSING_PACKAGES=!MISSING_PACKAGES! %%p
    )
)

if "!MISSING_PACKAGES!"=="" (
    call :log_success "所有依赖包已安装"
    goto :eof
)

call :log_warning "缺少以下依赖包:!MISSING_PACKAGES!"
call :log_info "正在尝试自动安装..."

REM 安装缺失的包
python -m pip install !MISSING_PACKAGES!
if errorlevel 1 (
    call :log_error "依赖包安装失败，请手动运行: python -m pip install!MISSING_PACKAGES!"
    exit /b 1
) else (
    call :log_success "依赖包安装成功"
)
goto :eof

REM 检查网络连通性
:check_network
call :log_info "检查网络连通性..."

REM 检查 https://app.warp.dev 的连通性
curl -s --connect-timeout 10 --max-time 30 https://app.warp.dev >nul 2>&1
if %errorlevel%==0 (
    call :log_success "网络连通性检查通过"
    echo ✅ 运行时请保证 https://app.warp.dev 网络联通性
) else (
    call :log_warning "网络连通性检查失败，请确保可以访问 https://app.warp.dev"
    echo ⚠️ 运行时请保证 https://app.warp.dev 网络联通性
    echo    如果网络连接失败，服务可能无法正常工作
)

REM 终端即时测试联通性并打印结果
set "HTTP_CODE="
set "RTT="
for /f "tokens=1,2" %%a in ('curl -s -o NUL -w "%%{http_code} %%{time_total}" https://app.warp.dev 2^>NUL') do (
    set "HTTP_CODE=%%a"
    set "RTT=%%b"
)
if "%HTTP_CODE%"=="200" (
    echo 🌐 当前 https://app.warp.dev 联通: 是 (HTTP %HTTP_CODE%, 耗时 %RTT%s)
) else if "%HTTP_CODE%"=="301" (
    echo 🌐 当前 https://app.warp.dev 联通: 是 (HTTP %HTTP_CODE%, 耗时 %RTT%s)
) else if "%HTTP_CODE%"=="302" (
    echo 🌐 当前 https://app.warp.dev 联通: 是 (HTTP %HTTP_CODE%, 耗时 %RTT%s)
) else (
    echo 🌐 当前 https://app.warp.dev 联通: 否 (HTTP %HTTP_CODE%)
)
goto :eof

REM 启动Protobuf桥接服务器
:start_bridge_server
call :log_info "启动Protobuf桥接服务器..."

REM 使用小众端口28888避免与其他应用冲突
set BRIDGE_PORT=28888

REM 检查端口是否被占用
netstat -an | find "%BRIDGE_PORT%" >nul 2>&1
if %errorlevel%==0 (
    call :log_warning "端口%BRIDGE_PORT%已被占用，尝试终止现有进程..."
    for /f "tokens=5" %%a in ('netstat -ano ^| find "%BRIDGE_PORT%"') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    timeout /t 2 >nul
)

REM 启动服务器（后台运行）
start /B uv run warp2api-bridge --port %BRIDGE_PORT% > bridge_server.log 2>&1
set BRIDGE_PID=%errorlevel%

REM 等待服务器启动
call :log_info "等待Protobuf桥接服务器启动..."
for /l %%i in (1,1,30) do (
    curl -s http://localhost:%BRIDGE_PORT%/healthz >nul 2>&1
    if %errorlevel%==0 (
        call :log_success "Protobuf桥接服务器启动成功 (PID: %BRIDGE_PID%)"
        call :log_info "📍 Protobuf桥接服务器地址: http://localhost:%BRIDGE_PORT%"
        goto :bridge_started
    )
    timeout /t 1 >nul
)

call :log_error "Protobuf桥接服务器启动失败"
type bridge_server.log
exit /b 1

:bridge_started
goto :eof

REM 启动多协议网关服务器
:start_openai_server
call :log_info "启动多协议网关服务器..."

REM 使用小众端口28889避免与其他应用冲突
set OPENAI_PORT=28889

REM 检查端口是否被占用
netstat -an | find "%OPENAI_PORT%" >nul 2>&1
if %errorlevel%==0 (
    call :log_warning "端口%OPENAI_PORT%已被占用，尝试终止现有进程..."
    for /f "tokens=5" %%a in ('netstat -ano ^| find "%OPENAI_PORT%"') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    timeout /t 2 >nul
)

REM 启动服务器（后台运行）
start /B uv run warp2api-gateway --port %OPENAI_PORT% > gateway_server.log 2>&1
set OPENAI_PID=%errorlevel%

REM 等待服务器启动
call :log_info "等待多协议网关服务器启动..."
for /l %%i in (1,1,30) do (
    curl -s http://localhost:%OPENAI_PORT%/healthz >nul 2>&1
    if %errorlevel%==0 (
        call :log_success "多协议网关服务器启动成功 (PID: %OPENAI_PID%)"
        call :log_info "📍 多协议网关服务器地址: http://localhost:%OPENAI_PORT%"
        goto :openai_started
    )
    timeout /t 1 >nul
)

call :log_error "多协议网关服务器启动失败"
type gateway_server.log
exit /b 1

:openai_started
goto :eof

REM 显示服务器状态
:show_status
echo.
echo ============================================
echo 🚀 warp2api 服务器状态
echo ============================================
echo 📍 Protobuf桥接服务器: http://localhost:28888
echo 📍 多协议网关服务器: http://localhost:28889
echo 📍 API文档: http://localhost:28889/docs
echo 🔗 Roocode / KiloCode baseUrl: http://127.0.0.1:28889/v1
echo ⬇️ KilloCode 下载地址：https://app.kilocode.ai/users/sign_up?referral-code=df16bc60-be35-480f-be2c-b1c6685b6089
echo.
echo 🔧 支持的模型:http://127.0.0.1:28889/v1/models
echo    • claude-4-sonnet
echo    • claude-4.5-opus
echo    • claude-4.6-opus
echo    • claude-4.1-opus
echo    • gemini-2.5-pro
echo    • gpt-5.1
echo    • gpt-5.2
echo    • gpt-5
echo    • gpt-5.3-codex
echo.
setlocal enabledelayedexpansion
    <nul set /p="🔑 当前API接口Token: "
if exist ".env" (
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="API_TOKEN" (
            set "API_TOKEN=%%b"
            set "API_TOKEN=!API_TOKEN:"=!"
        )
    )
    if defined API_TOKEN (
        echo !API_TOKEN!
    ) else (
        echo 未设置
    )
) else (
    echo .env 文件不存在
)
    endlocal
echo.
echo 📝 测试命令:
echo curl -X POST http://localhost:28889/v1/chat/completions \
echo   -H "Content-Type: application/json" \
echo   -H "Authorization: Bearer !API_TOKEN!" \
echo   -d "{\"model\": \"claude-4-sonnet\", \"messages\": [{\"role\": \"user\", \"content\": \"你好\"}], \"stream\": true}"
echo.
echo 🛑 要停止服务器，请运行: stop.bat
echo ============================================
goto :eof

REM 主函数
REM 自动配置环境变量
call :auto_configure

:main
echo ============================================
echo 🚀 warp2api Windows 快速启动脚本
echo ============================================

REM 检查命令行参数
if "%1"=="stop" goto stop_servers

REM 检查环境
call :check_python
call :check_dependencies
call :check_network

REM 启动服务器
call :start_bridge_server
call :start_openai_server

REM 显示状态信息
call :show_status

if "%W2A_VERBOSE%"=="true" (
    call :log_success "warp2api启动完成！"
    call :log_info "服务器正在后台运行，按 Ctrl+C 退出"
    echo.
    echo 📋 实时日志监控 (按 Ctrl+C 退出):
    echo ----------------------------------------
    echo 提示: 日志文件保存在 bridge_server.log 和 gateway_server.log
    echo 可以使用以下命令查看最新日志:
    echo   • type bridge_server.log
    echo   • type gateway_server.log
    echo.
    echo 显示最近的日志内容:
    echo.
    echo === Protobuf桥接服务器日志 ===
    if exist "bridge_server.log" (
        type bridge_server.log | findstr /r /c:".*" | tail -n 10 2>nul || type bridge_server.log
    ) else (
        echo 日志文件尚未生成
    )
    echo.
    echo === 多协议网关服务器日志 ===
    if exist "gateway_server.log" (
        type gateway_server.log | findstr /r /c:".*" | tail -n 10 2>nul || type gateway_server.log
    ) else (
        echo 日志文件尚未生成
    )
    echo.
    pause
) else (
    call :log_success "warp2api启动完成！服务器正在后台运行。"
)
goto :eof

REM 停止服务器
:stop_servers
call :log_info "停止所有服务器..."

REM 停止Python服务器进程
call :log_info "终止Python服务器进程..."
taskkill /F /IM python.exe >nul 2>&1

REM 停止端口相关的进程（使用小众端口）
call :log_info "清理端口进程..."
for /f "tokens=5" %%a in ('netstat -ano ^| find "28888"') do (
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| find "28889"') do (
    taskkill /PID %%a /F >nul 2>&1
)

call :log_success "所有服务器已停止"
goto :eof

REM 执行主函数
call :main %*
