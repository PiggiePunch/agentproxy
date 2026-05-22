#!/bin/bash

echo "🚀 OpenClaw Proxy Server - 重构版本启动脚本"
echo "=========================================="

# 检查Python版本
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到 Python3，请先安装 Python3"
    exit 1
fi

# 检查项目目录
if [ ! -f "backend/main.py" ]; then
    echo "❌ 错误: 请在项目根目录运行此脚本"
    exit 1
fi

# 加载环境变量（如果存在）
if [ -f ".env" ]; then
    echo "✓ 加载环境变量配置"
    export $(cat .env | grep -v '^#' | xargs)
fi

echo "📂 工作目录: $(pwd)"
echo "🐍 Python版本: $(python3 --version)"
echo ""

# 启动服务器
python3 backend/main.py