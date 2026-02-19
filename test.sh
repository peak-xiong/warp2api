#!/bin/bash

# warp2api 对外接口测试脚本
# 只测试对外API接口功能

set -e

# 从 .env 文件加载环境变量（如果存在）
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 环境变量控制日志输出，默认不打印日志
# 设置 W2A_VERBOSE=true 来启用详细日志输出
VERBOSE="${W2A_VERBOSE:-false}"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 日志函数
log_info() {
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $1${NC}"
    fi
}

log_success() {
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1${NC}"
    fi
}

log_warning() {
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
    fi
}

log_error() {
    # 错误信息始终显示，即使在静默模式下
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

if [ "$VERBOSE" = "true" ]; then
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}🚀 warp2api 对外接口测试${NC}"
    echo -e "${BLUE}==========================================${NC}"

    # 检查API服务器是否运行
    echo -e "${YELLOW}检查API服务器状态...${NC}"
fi

if curl -s http://localhost:28889/healthz >/dev/null 2>&1; then
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${GREEN}✅ 多协议网关服务器 (28889) 运行正常${NC}"
    fi
else
    log_error "多协议网关服务器 (28889) 未响应"
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${YELLOW}请先运行 ./start.sh 启动服务器${NC}"
    fi
    exit 1
fi

# 测试API接口
if [ "$VERBOSE" = "true" ]; then
    echo -e "\n${YELLOW}测试API接口...${NC}"
fi

# 获取API Token
API_TOKEN=""
if [ -f ".env" ]; then
    API_TOKEN=$(grep "^API_TOKEN=" .env | cut -d'=' -f2- | sed 's/^"//' | sed 's/"$//')
fi

if [ -z "$API_TOKEN" ]; then
    API_TOKEN="0000"
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${YELLOW}⚠️  未找到API_TOKEN，使用默认值: $API_TOKEN${NC}"
    fi
fi

# 测试chat completions接口
if [ "$VERBOSE" = "true" ]; then
    echo -e "${BLUE}测试 /v1/chat/completions 接口...${NC}"
fi
RESPONSE=$(curl -s -X POST http://localhost:28889/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_TOKEN" \
  -d '{
    "model": "claude-4-sonnet",
    "messages": [{"role": "user", "content": "Say hello in one word"}],
    "max_tokens": 10,
    "stream": false
  }')

if echo "$RESPONSE" | grep -q '"choices"'; then
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${GREEN}✅ Chat completions 接口正常${NC}"
    fi
else
    log_error "Chat completions 接口异常"
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${YELLOW}响应内容: $RESPONSE${NC}"
    fi
fi

# 测试models接口
if [ "$VERBOSE" = "true" ]; then
    echo -e "${BLUE}测试 /v1/models 接口...${NC}"
fi
MODELS_RESPONSE=$(curl -s http://localhost:28889/v1/models)

if echo "$MODELS_RESPONSE" | grep -q '"data"'; then
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${GREEN}✅ Models 接口正常${NC}"
    fi
else
    log_error "Models 接口异常"
    if [ "$VERBOSE" = "true" ]; then
        echo -e "${YELLOW}响应内容: $MODELS_RESPONSE${NC}"
    fi
fi

if [ "$VERBOSE" = "true" ]; then
    echo -e "\n${GREEN}🎉 对外接口测试完成！${NC}"
    echo -e "${BLUE}==========================================${NC}"
fi
