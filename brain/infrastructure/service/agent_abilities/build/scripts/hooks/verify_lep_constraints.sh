#!/bin/bash
# 验证所有 agent CLAUDE.md 包含 LEP constraints

set -e

echo "========================================
验证 LEP Constraints 部署
========================================
"

TOTAL_COUNT=0
VALID_COUNT=0
MISSING_COUNT=0
MISSING_FILES=()

# 检查所有 agent CLAUDE.md
while IFS= read -r file; do
    TOTAL_COUNT=$((TOTAL_COUNT + 1))

    if grep -q "## LEP Gates 强制约束" "$file"; then
        VALID_COUNT=$((VALID_COUNT + 1))
        echo "✅ $file"
    else
        MISSING_COUNT=$((MISSING_COUNT + 1))
        MISSING_FILES+=("$file")
        echo "❌ $file - 缺少 LEP constraints"
    fi
done < <(find /brain/groups -name "CLAUDE.md" -type f)

echo ""
echo "检查 base_template.md..."
if grep -q "## LEP Gates 强制约束" "/brain/base/spec/templates/agent/base_template.md"; then
    echo "✅ /brain/base/spec/templates/agent/base_template.md"
else
    echo "❌ /brain/base/spec/templates/agent/base_template.md - 缺少 LEP constraints"
    MISSING_COUNT=$((MISSING_COUNT + 1))
fi

echo ""
echo "========================================"
echo "验证结果"
echo "  总计: $TOTAL_COUNT 个 agent CLAUDE.md"
echo "  ✅ 包含约束: $VALID_COUNT"
echo "  ❌ 缺少约束: $MISSING_COUNT"
echo "========================================"

if [ $MISSING_COUNT -gt 0 ]; then
    echo ""
    echo "缺少约束的文件："
    for f in "${MISSING_FILES[@]}"; do
        echo "  - $f"
    done
    exit 1
fi

echo ""
echo "✅ 所有文件验证通过！"
exit 0
