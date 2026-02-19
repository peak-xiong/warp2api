@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM warp2api Windows 对外接口测试脚本
REM 只测试对外API接口功能

REM 从 .env 文件加载环境变量（如果存在）
if exist ".env" (
    for /f "tokens=*" %%i in (.env) do (
        set "%%i"
    )
)

REM 环境变量控制日志输出，默认不打印日志
REM 设置 W2A_VERBOSE=true 来启用详细日志输出
if "%W2A_VERBOSE%"=="" set "W2A_VERBOSE=false"

REM 颜色定义（Windows CMD不支持ANSI颜色，移除以保持一致性）

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

if "%W2A_VERBOSE%"=="true" (
    echo ============================================
    echo 🚀 warp2api 对外接口测试
    echo ============================================

    REM 检查API服务器是否运行
    echo 检查API服务器状态...
)

if exist ".env" (
    REM 获取API_TOKEN
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="API_TOKEN" (
            set "API_TOKEN=%%b"
            set "API_TOKEN=!API_TOKEN:"=!"
        )
    )
)

curl -s http://localhost:28889/healthz >nul 2>&1
if %errorlevel% neq 0 (
    call :log_error "OpenAI兼容API服务器 (28889) 未响应"
    if "%W2A_VERBOSE%"=="true" (
        echo 请先运行 start.bat 启动服务器
    )
    exit /b 1
)

if "%W2A_VERBOSE%"=="true" (
    echo ✅ OpenAI兼容API服务器 (28889) 运行正常
)

REM 测试API接口
if "%W2A_VERBOSE%"=="true" (
    echo.
    echo 测试API接口...
)

REM 获取API Token
set "API_TOKEN="
if exist ".env" (
    for /f "tokens=1,* delims==" %%a in (.env) do (
        if "%%a"=="API_TOKEN" (
            set "API_TOKEN=%%b"
            set "API_TOKEN=!API_TOKEN:"=!"
        )
    )
)

if "!API_TOKEN!"=="" (
    set "API_TOKEN=0000"
    if "%W2A_VERBOSE%"=="true" (
        echo ⚠️ 未找到API_TOKEN，使用默认值: !API_TOKEN!
    )
)

REM 测试chat completions接口
if "%W2A_VERBOSE%"=="true" (
    echo 测试 /v1/chat/completions 接口...
)

curl -s -X POST http://localhost:28889/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -H "Authorization: Bearer !API_TOKEN!" ^
  -d "{\"model\": \"claude-4-sonnet\", \"messages\": [{\"role\": \"user\", \"content\": \"Say hello in one word\"}], \"max_tokens\": 10, \"stream\": false}" > response.json

findstr /C:"\"choices\"" response.json >nul 2>&1
if %errorlevel%==0 (
    if "%W2A_VERBOSE%"=="true" (
        call :log_success "Chat completions 接口正常"
    )
) else (
    call :log_error "Chat completions 接口异常"
    if "%W2A_VERBOSE%"=="true" (
        echo 响应内容:
        type response.json
    )
)

REM 测试models接口
if "%W2A_VERBOSE%"=="true" (
    echo 测试 /v1/models 接口...
)

curl -s http://localhost:28889/v1/models > models_response.json

findstr /C:"\"data\"" models_response.json >nul 2>&1
if %errorlevel%==0 (
    if "%W2A_VERBOSE%"=="true" (
        call :log_success "Models 接口正常"
    )
) else (
    call :log_error "Models 接口异常"
    if "%W2A_VERBOSE%"=="true" (
        echo 响应内容:
        type models_response.json
    )
)

REM 清理临时文件
del response.json 2>nul
del models_response.json 2>nul

if "%W2A_VERBOSE%"=="true" (
    echo.
    call :log_success "🎉 对外接口测试完成！"
    echo ============================================
)