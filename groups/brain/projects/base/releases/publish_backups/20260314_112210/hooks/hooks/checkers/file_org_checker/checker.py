#!/usr/bin/env python3
"""
文件组织检查器 - G-FILE-ORG

功能：
- 禁止顶层文件
- 禁止项目根目录文件
- 禁止无意义命名

完整版（TODO）:
- 三种组织模式验证（time_based, business_based, type_based）
- 命名约定检查
- 时间格式验证
"""
import re
from pathlib import Path
from typing import Tuple

# 例外路径（不检查）
EXCEPTIONS = [
    "/brain/runtime/tmp/",
    "/brain/.claude/",
    "/brain/.git/",
]

# 允许的顶层文件（特殊文件）
ALLOWED_TOPLEVEL = [
    "/brain/README.md",
    "/brain/INIT.yaml",
    "/brain/CLAUDE.md",
    "/brain/.gitignore",
    "/brain/Makefile",
]


def is_exception(file_path: str) -> bool:
    """检查是否是例外路径"""
    # memory/ 例外（任何位置）
    if "/memory/" in file_path:
        return True

    for exc in EXCEPTIONS:
        if file_path.startswith(exc):
            return True

    # 允许的顶层文件
    if file_path in ALLOWED_TOPLEVEL:
        return True

    return False


def check_toplevel_file(file_path: str) -> Tuple[bool, str]:
    """检查是否是禁止的顶层文件"""
    # 匹配 /brain/filename.ext
    pattern = r"^/brain/[^/]+\.(txt|md|yaml|json|py|sh|pdf|csv|log)$"
    if re.match(pattern, file_path):
        # 检查是否在允许列表
        if file_path not in ALLOWED_TOPLEVEL:
            return False, "禁止在 /brain/ 顶层创建文件"
    return True, ""


def check_project_root_file(file_path: str) -> Tuple[bool, str]:
    """检查是否是禁止的项目根目录文件"""
    # 匹配 /brain/groups/org/group_name/filename.ext
    pattern = r"^/brain/groups/[^/]+/[^/]+/[^/]+\.(txt|md|yaml|json|py|pdf|csv)$"
    if re.match(pattern, file_path):
        return False, "禁止在项目根目录创建文件（应放入子目录如 projects/, spec/, tasks/）"
    return True, ""


def check_meaningless_names(file_path: str) -> Tuple[bool, str]:
    """检查是否包含无意义的目录名"""
    meaningless = ["misc", "other", "temp", "untitled", "dump", "stuff"]

    path_parts = file_path.lower().split("/")
    for part in path_parts:
        if part in meaningless:
            return False, f"禁止使用无意义的目录名: {part}"

    return True, ""


def check_file_organization(file_path: str) -> Tuple[bool, str]:
    """
    检查文件组织是否符合规范

    返回:
        (is_valid, error_message)
    """
    # 例外路径不检查
    if is_exception(file_path):
        return True, ""

    # 1. 禁止顶层文件
    is_valid, error_msg = check_toplevel_file(file_path)
    if not is_valid:
        return False, error_msg

    # 2. 禁止项目根目录文件
    is_valid, error_msg = check_project_root_file(file_path)
    if not is_valid:
        return False, error_msg

    # 3. 禁止无意义命名
    is_valid, error_msg = check_meaningless_names(file_path)
    if not is_valid:
        return False, error_msg

    # 通过所有检查
    return True, ""


# 测试
if __name__ == "__main__":
    test_cases = [
        ("/brain/test.txt", False, "顶层文件"),
        ("/brain/README.md", True, "允许的顶层文件"),
        ("/brain/groups/org/xkquant/report.pdf", False, "项目根目录文件"),
        ("/brain/groups/org/xkquant/projects/newsalpha/report.pdf", True, "正确的项目文件"),
        ("/brain/runtime/misc/test.txt", False, "无意义命名"),
        ("/brain/runtime/logs/2026/02/13/test.log", True, "正确的日志文件"),
        ("/brain/runtime/tmp/test.txt", True, "例外路径"),
        ("/brain/groups/org/xkquant/memory/test.md", True, "memory 例外"),
    ]

    print("=== File Organization Checker Tests ===")
    for path, expected_valid, desc in test_cases:
        is_valid, error_msg = check_file_organization(path)
        status = "✅" if is_valid == expected_valid else "❌"
        print(f"{status} {desc}")
        print(f"   Path: {path}")
        print(f"   Result: {'PASS' if is_valid else 'BLOCK'}")
        if not is_valid:
            print(f"   Reason: {error_msg}")
        print()
