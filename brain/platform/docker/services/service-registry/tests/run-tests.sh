#!/bin/bash
# 服务注册中心测试脚本
# 在隔离环境中运行完整测试

set -e

echo "================================"
echo "服务注册中心 - 隔离测试环境"
echo "================================"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Step 1: 清理旧环境${NC}"
docker compose -p service-registry-test down -v 2>/dev/null || true
docker network rm service-registry-test-net 2>/dev/null || true

echo ""
echo -e "${YELLOW}Step 2: 构建镜像${NC}"
docker compose build

echo ""
echo -e "${YELLOW}Step 3: 启动测试环境${NC}"
docker compose up -d service-registry mock-gateway mock-task-manager

echo ""
echo -e "${YELLOW}Step 4: 等待服务就绪${NC}"
sleep 10

# 检查注册中心健康
echo "检查注册中心健康状态..."
for i in {1..10}; do
    if curl -s http://localhost:18500/health > /dev/null 2>&1; then
        echo -e "${GREEN}注册中心已就绪${NC}"
        break
    fi
    echo "等待中... ($i/10)"
    sleep 2
done

echo ""
echo -e "${YELLOW}Step 5: 运行测试${NC}"
docker compose run --rm test-runner

echo ""
echo -e "${YELLOW}Step 6: 获取测试结果${NC}"
docker compose cp test-runner:/results/test-report.json ./test-report.json 2>/dev/null || true

if [ -f "./test-report.json" ]; then
    echo -e "${GREEN}测试报告已保存: ./test-report.json${NC}"
    echo ""
    echo "测试摘要:"
    cat ./test-report.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
summary = data.get('summary', {})
print(f\"  总计: {summary.get('total', 0)}\")
print(f\"  通过: {summary.get('passed', 0)}\")
print(f\"  失败: {summary.get('failed', 0)}\")
print(f\"  跳过: {summary.get('skipped', 0)}\")
print(f\"  用时: {summary.get('duration', 0):.2f}s\")
" 2>/dev/null || echo "  (需要 python3 解析报告)"
else
    echo -e "${YELLOW}测试报告未生成${NC}"
fi

echo ""
echo -e "${YELLOW}Step 7: 查看服务状态${NC}"
echo "注册中心中的服务:"
curl -s http://localhost:18500/api/v1/registry/services | python3 -m json.tool 2>/dev/null || curl -s http://localhost:18500/api/v1/registry/services

echo ""
echo -e "${YELLOW}Step 8: 清理测试环境${NC}"
read -p "是否清理测试环境? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose -p service-registry-test down -v
    echo -e "${GREEN}测试环境已清理${NC}"
else
    echo -e "${YELLOW}保留测试环境，可手动访问:"
    echo "  注册中心: http://localhost:18500"
    echo "  Gateway: http://localhost:18080 (映射需添加)"
    echo -e "  清理命令: docker compose -p service-registry-test down -v${NC}"
fi

echo ""
echo "================================"
echo "测试完成"
echo "================================"
