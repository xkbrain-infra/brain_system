#!/usr/bin/env python3
"""YAML Loader - 简单的 YAML 加载器（避免依赖 pyyaml）"""
import re
from pathlib import Path
from typing import Dict, Any, List


def load_yaml_rules(yaml_path: Path) -> Dict[str, Any]:
    """
    简单的 YAML 加载器
    只解析我们需要的字段：forbidden_patterns, allowed_patterns, content_triggers
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            content = f.read()

        result = {
            'forbidden_patterns': _extract_list(content, 'forbidden_patterns'),
            'allowed_patterns': _extract_list(content, 'allowed_patterns'),
            'content_triggers': _extract_list(content, 'content_triggers')
        }

        return result

    except Exception as e:
        # 规则文件不存在或解析失败，返回空规则
        return {
            'forbidden_patterns': [],
            'allowed_patterns': [],
            'content_triggers': []
        }


def _extract_list(content: str, key: str) -> List[str]:
    """提取 YAML 列表项"""
    result = []
    in_section = False

    for line in content.split('\n'):
        if f'{key}:' in line:
            in_section = True
            continue

        if in_section:
            if line.strip().startswith('-'):
                # 提取引号中的内容
                match = re.search(r'["\']([^"\']+)["\']', line)
                if match:
                    result.append(match.group(1))
            elif line.strip() and not line.strip().startswith('#'):
                # 遇到非列表项，结束
                if not line.startswith(' ') or ':' in line:
                    in_section = False

    return result
