#!/bin/bash
# ============================================================
# 一键同步代码到远程服务器并运行 DM8 测试
# 用法: ./scripts/deploy_and_test_dm8.sh [test_filter]
# 示例:
#   ./scripts/deploy_and_test_dm8.sh              # 运行所有 DM8 测试
#   ./scripts/deploy_and_test_dm8.sh test_connection  # 仅运行连接测试
# ============================================================

set -e

SERVER="root@114.232.68.44"
REMOTE_DIR="/opt/db-compatibility-demo"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEST_FILTER="${1:-dm8}"

# 密码从环境变量读取，否则提示输入
SSH_PASS="${DM8_SERVER_PASS:-}"
if [ -z "$SSH_PASS" ]; then
    read -sp "SSH password for $SERVER: " SSH_PASS
    echo
fi

export SSH_PASS

echo "=========================================="
echo "  同步代码到 $SERVER"
echo "=========================================="

expect -c "
set timeout 120
spawn rsync -avz \
    --exclude .venv \
    --exclude __pycache__ \
    --exclude .git \
    --exclude node_modules \
    --exclude '*.egg-info' \
    --exclude .env.local \
    -e \"ssh -o StrictHostKeyChecking=no\" \
    $LOCAL_DIR/ $SERVER:$REMOTE_DIR/
expect \"password:\"
send \"\$SSH_PASS\r\"
expect eof
"

echo ""
echo "=========================================="
echo "  在服务器上运行 DM8 测试"
echo "=========================================="

expect -c "
set timeout 300
spawn ssh -o StrictHostKeyChecking=no $SERVER \"
    cd $REMOTE_DIR && \
    source .venv/bin/activate && \
    export DM_HOME=/opt/dmdbms && \
    export LD_LIBRARY_PATH=/opt/dmdbms/bin:\\\$LD_LIBRARY_PATH && \
    python -m pytest tests/ -v -m $TEST_FILTER 2>&1 || \
    python -m pytest tests/ -v -k $TEST_FILTER 2>&1
\"
expect \"password:\"
send \"\$SSH_PASS\r\"
expect eof
"

echo ""
echo "=========================================="
echo "  完成"
echo "=========================================="
