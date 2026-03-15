#!/usr/bin/env python3
"""
路径检查器 - 验证文件路径是否符合规则

功能：
- 读取 YAML 规则文件
- 检查路径是否在禁止/允许列表中
- 支持 glob 模式匹配
- 返回检查结果和错误消息

规则来源优先级：
1. lep.yaml (G-SPEC-LOCATION.enforcement.patterns) - 推荐
2. spec_path.yaml (兼容性 fallback)
"""
import re
import sys
from pathlib import Path
from typing import Tuple, List, Dict, Any
import fnmatch

# 尝试导入 lep 模块
try:
    LEP_MODULE_PATH = Path(__file__).parent.parent.parent.parent.parent / "lep"
    sys.path.insert(0, str(LEP_MODULE_PATH))
    from lep import load_lep
    _LEP_AVAILABLE = True
except ImportError:
    _LEP_AVAILABLE = False


def load_lep_rules() -> Dict[str, Any]:
    """
    从 lep.yaml 加载 G-SPEC-LOCATION 规则（推荐方式）

    返回:
        {
            'forbidden_patterns': List[str],
            'allowed_patterns': List[str],
            'content_triggers': List[str],
            'source': 'lep.yaml'
        }
    """
    if not _LEP_AVAILABLE:
        return None

    try:
        lep = load_lep()
        gate = lep.gates.get('G-SPEC-LOCATION')

        if not gate or 'enforcement' not in gate:
            return None

        enforcement = gate['enforcement']

        # 提取 patterns
        patterns = enforcement.get('patterns', {})
        forbidden = patterns.get('forbidden', [])
        allowed = patterns.get('allowed', [])

        # 提取 content_triggers
        content_triggers = enforcement.get('content_triggers', [])

        return {
            'forbidden_patterns': forbidden,
            'allowed_patterns': allowed,
            'content_triggers': content_triggers,
            'source': 'lep.yaml'
        }

    except Exception as e:
        # lep.yaml 加载失败，返回 None 以 fallback
        print(f"Warning: Failed to load rules from lep.yaml: {e}", file=sys.stderr)
        return None


def load_yaml_rules(yaml_path: Path) -> Dict[str, Any]:
    """
    简单的 YAML 加载器（避免依赖 pyyaml）
    只解析我们需要的字段
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取 forbidden_patterns
        forbidden_patterns = []
        in_forbidden = False
        for line in content.split('\n'):
            if 'forbidden_patterns:' in line:
                in_forbidden = True
                continue
            if in_forbidden:
                if line.strip().startswith('-'):
                    # 提取引号中的内容
                    match = re.search(r'["\']([^"\']+)["\']', line)
                    if match:
                        forbidden_patterns.append(match.group(1))
                elif line.strip() and not line.strip().startswith('#'):
                    # 遇到非列表项，结束
                    if not line.startswith(' ') or ':' in line:
                        in_forbidden = False

        # 提取 allowed_patterns
        allowed_patterns = []
        in_allowed = False
        for line in content.split('\n'):
            if 'allowed_patterns:' in line:
                in_allowed = True
                continue
            if in_allowed:
                if line.strip().startswith('-'):
                    match = re.search(r'["\']([^"\']+)["\']', line)
                    if match:
                        allowed_patterns.append(match.group(1))
                elif line.strip() and not line.strip().startswith('#'):
                    if not line.startswith(' ') or ':' in line:
                        in_allowed = False

        # 提取 content_triggers
        content_triggers = []
        in_triggers = False
        for line in content.split('\n'):
            if 'content_triggers:' in line:
                in_triggers = True
                continue
            if in_triggers:
                if line.strip().startswith('-'):
                    match = re.search(r'["\']([^"\']+)["\']', line)
                    if match:
                        content_triggers.append(match.group(1))
                elif line.strip() and not line.strip().startswith('#'):
                    if not line.startswith(' ') or ':' in line:
                        in_triggers = False

        return {
            'forbidden_patterns': forbidden_patterns,
            'allowed_patterns': allowed_patterns,
            'content_triggers': content_triggers
        }

    except Exception as e:
        # 规则文件不存在或解析失败，返回空规则
        return {
            'forbidden_patterns': [],
            'allowed_patterns': [],
            'content_triggers': []
        }


def matches_pattern(path: str, pattern: str) -> bool:
    """
    检查路径是否匹配 glob 模式

    支持：
    - * : 匹配任意字符（不包括 /）
    - ** : 匹配任意字符（包括 /）
    - ? : 匹配单个字符
    """
    # 将 ** 转换为特殊标记
    pattern = pattern.replace('**', '<DOUBLESTAR>')

    # 将 * 转换为 [^/]*
    pattern = pattern.replace('*', '[^/]*')

    # 将 <DOUBLESTAR> 转换为 .*
    pattern = pattern.replace('<DOUBLESTAR>', '.*')

    # 将 ? 转换为 .
    pattern = pattern.replace('?', '.')

    # 编译正则
    regex = re.compile(f'^{pattern}$')

    return bool(regex.match(path))


def is_forbidden(path: str, forbidden_patterns: List[str]) -> Tuple[bool, str]:
    """检查路径是否在禁止列表中"""
    for pattern in forbidden_patterns:
        if matches_pattern(path, pattern):
            return True, pattern
    return False, ""


def is_allowed(path: str, allowed_patterns: List[str]) -> bool:
    """检查路径是否在允许列表中"""
    for pattern in allowed_patterns:
        if matches_pattern(path, pattern):
            return True
    return False


def check_spec_path(file_path: str, rules_yaml: Path = None) -> Tuple[bool, str]:
    """
    检查文件路径是否符合 SPEC 规则

    规则来源优先级：
    1. lep.yaml (G-SPEC-LOCATION) - 推荐
    2. spec_path.yaml (fallback，兼容性)

    返回:
        (is_valid, error_message)
        - is_valid: True 表示路径合规，False 表示违规
        - error_message: 如果违规，返回错误消息
    """
    # 1. 优先从 lep.yaml 加载规则
    rules = load_lep_rules()
    rules_source = "lep.yaml"

    # 2. Fallback 到 spec_path.yaml（兼容性）
    if rules is None and rules_yaml and rules_yaml.exists():
        rules = load_yaml_rules(rules_yaml)
        rules_source = str(rules_yaml)

    # 3. 如果两个都失败，使用空规则（通过所有检查）
    if rules is None:
        rules = {
            'forbidden_patterns': [],
            'allowed_patterns': [],
            'content_triggers': []
        }
        rules_source = "none (default allow)"

    forbidden_patterns = rules['forbidden_patterns']
    allowed_patterns = rules['allowed_patterns']

    # 排除合法写入路径（这些路径即使含 "spec" 也不是 SPEC 文档）
    EXCLUDED_PREFIXES = [
        "/brain/runtime/update_brain/pending/",  # update_brain pending 机制
        "/brain/runtime/update_brain/archive/",  # update_brain 归档
        "/root/.claude/projects/",              # memory 文件（非 spec）
    ]
    for prefix in EXCLUDED_PREFIXES:
        if file_path.startswith(prefix):
            return True, ""

    # 仅对 spec 相关文件生效
    is_spec_file = (
        "/spec/" in file_path
        or "/specs/" in file_path
        or "spec" in Path(file_path).name.lower()
    )
    if not is_spec_file:
        return True, ""

    # 如果没有规则，允许通过
    if not forbidden_patterns and not allowed_patterns:
        return True, ""

    # 1. 检查是否在禁止列表
    is_forbidden_path, matched_pattern = is_forbidden(file_path, forbidden_patterns)

    if is_forbidden_path:
        # 提取禁止位置描述
        forbidden_location = matched_pattern.replace('**/', '').replace('/**', '')

        error_msg = f"""
🚫 SPEC 路径违规 (G-SPEC-LOCATION)

文件路径: {file_path}
匹配规则: {matched_pattern}

❌ 禁止在 {forbidden_location} 创建 SPEC 文件
✅ 正确路径格式: /brain/groups/org/{{group}}/spec/{{spec_id}}/

SPEC 文件必须遵循 S1-S8 流程：
1. 创建 SPEC 目录: /brain/groups/org/{{group}}/spec/BS-{{seq}}-{{short_name}}/
2. 写入标准文件: 00_index.yaml → 08_complete.yaml
3. 经 PMO 审批后实施

参考文档:
- Workflow: /brain/base/spec/core/workflow.yaml
- Templates: /brain/base/spec/templates/
- 现有示例: /brain/groups/org/brain_system/spec/

规则来源: {rules_source}
"""
        return False, error_msg

    # 2. 检查是否在允许列表
    if allowed_patterns:
        if not is_allowed(file_path, allowed_patterns):
            error_msg = f"""
⚠️ SPEC 路径不在允许列表中

文件路径: {file_path}

允许的路径格式：
{chr(10).join(f'  - {p}' for p in allowed_patterns)}

建议：
1. 检查路径是否正确
2. 确认 group 名称是否存在
3. 确认 spec_id 格式是否正确

规则来源: {rules_source}
参考: /brain/base/spec/core/lep.yaml (G-SPEC-LOCATION)
"""
            return False, error_msg

    # 通过所有检查
    return True, ""


def should_check_content(file_path: str, content_triggers: List[str]) -> bool:
    """
    检查文件是否应该进行内容检查
    （根据 content_triggers 判断）

    注：此函数需要读取文件内容，暂未实现
    """
    # TODO: 读取文件内容并检查关键词
    # 目前先基于文件扩展名判断
    return file_path.endswith('.yaml') or file_path.endswith('.md')


# 测试代码
if __name__ == "__main__":
    # 测试路径匹配
    test_cases = [
        ("/root/.claude/plans/test.md", "**/.claude/plans/**", True),
        ("/brain/groups/org/brain_system/spec/BS-001/test.yaml", "/brain/groups/*/spec/**", True),
        ("/tmp/spec/test.yaml", "**/tmp/**", True),
        ("/brain/groups/org/xkquant/spec/XQ-001/test.yaml", "/brain/groups/org/xkquant/spec/**", True),
    ]

    print("=== Path Matcher Tests ===")
    for path, pattern, expected in test_cases:
        result = matches_pattern(path, pattern)
        status = "✅" if result == expected else "❌"
        print(f"{status} Pattern: {pattern}")
        print(f"   Path: {path}")
        print(f"   Result: {result}, Expected: {expected}\n")
