#!/usr/bin/env python3
"""
环境变量配置加载器
从 infrastructure/config 的配置源索引解析来源，并生成运行时环境变量到 /xkagent_infra/runtime/config/

用法:
    loader_env_vars.py --reload        # 重新加载所有配置
    loader_env_vars.py --validate      # 仅验证配置完整性
    loader_env_vars.py --reload --quiet  # 静默模式
"""

import os
import sys
import argparse
import yaml
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from collections import defaultdict


# ============================================================
# 路径定义
# ============================================================
SECRETS_ROOT = Path("/brain/secrets")
INFRA_CONFIG_ROOT = Path("/brain/infrastructure/config")
RUNTIME_ENV_SOURCE_ROOT = INFRA_CONFIG_ROOT / "runtime_env"
RUNTIME_CONFIG_ROOT = Path("/xkagent_infra/runtime/config")
RUNTIME_LOGS = Path("/xkagent_infra/runtime/logs")

PRIMARY_SOURCE_INDEX = RUNTIME_ENV_SOURCE_ROOT / "index.yaml"
RUNTIME_ENV_FILE = RUNTIME_CONFIG_ROOT / ".env"
RUNTIME_SOURCES = RUNTIME_CONFIG_ROOT / "sources.yaml"
RUNTIME_TIMESTAMP = RUNTIME_CONFIG_ROOT / "loaded_at.txt"
AUDIT_LOG = RUNTIME_LOGS / "config_audit.jsonl"


# ============================================================
# 配置加载器
# ============================================================
class EnvVarsLoader:
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.env_vars: Dict[str, str] = {}
        self.sources: Dict[str, dict] = {}
        self.errors: List[str] = []
        self.conflicts: List[dict] = []
        self.source_index_path: Path | None = None

    def log(self, message: str):
        """打印日志（如果非静默模式）"""
        if self.verbose:
            print(f"[INFO] {message}")

    def error(self, message: str):
        """记录错误"""
        self.errors.append(message)
        print(f"[ERROR] {message}", file=sys.stderr)

    def load_source_index(self) -> dict:
        """读取配置源索引，仅接受 infrastructure/config/runtime_env/index.yaml"""
        if not PRIMARY_SOURCE_INDEX.exists():
            self.error(f"Config source index not found: {PRIMARY_SOURCE_INDEX}")
            return {}

        try:
            with open(PRIMARY_SOURCE_INDEX, 'r') as f:
                index = yaml.safe_load(f)
                self.source_index_path = PRIMARY_SOURCE_INDEX
                self.log(f"Loaded config source index: {PRIMARY_SOURCE_INDEX}")
                return index or {}
        except Exception as e:
            self.error(f"Failed to load source index {PRIMARY_SOURCE_INDEX}: {e}")
            return {}

    def parse_env_file(self, env_file: Path) -> Dict[str, str]:
        """解析 .env 文件"""
        env_vars = {}

        if not env_file.exists():
            return env_vars

        try:
            with open(env_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    # 跳过空行和注释
                    if not line or line.startswith('#'):
                        continue

                    # 解析 KEY=VALUE
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()

                        # 移除引号
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        env_vars[key] = value
                    else:
                        self.error(f"Invalid line in {env_file}:{line_num}: {line}")

            return env_vars

        except Exception as e:
            self.error(f"Failed to parse {env_file}: {e}")
            return {}

    def scan_category(self, category: str, category_info: dict) -> Dict[str, Tuple[str, str]]:
        """
        扫描某个分类下的所有 .env 文件
        返回: {env_var_name: (value, source_path)}
        """
        result = {}
        category_path = SECRETS_ROOT / category

        if not category_path.exists():
            self.log(f"Category directory not found: {category_path}")
            return result

        # 获取该分类的文件列表
        files = category_info.get('files', [])

        for file_info in files:
            file_name = file_info.get('name', '')

            # 只处理 .env 文件
            if not file_name.endswith('.env'):
                continue

            file_path = category_path / file_name

            if not file_path.exists():
                self.log(f"File not found: {file_path}")
                continue

            # 检查文件权限
            file_stat = file_path.stat()
            file_mode = oct(file_stat.st_mode)[-3:]

            if file_mode not in ['600', '644']:
                self.error(f"Insecure file permissions {file_mode} for {file_path}")

            # 解析环境变量
            env_vars = self.parse_env_file(file_path)

            for key, value in env_vars.items():
                source = str(file_path)

                # 检测冲突
                if key in result:
                    old_value, old_source = result[key]
                    self.conflicts.append({
                        'var': key,
                        'old_value': old_value,
                        'old_source': old_source,
                        'new_value': value,
                        'new_source': source
                    })
                    self.log(f"Conflict: {key} overridden from {old_source} to {source}")

                result[key] = (value, source)

        return result

    def load_all_env_vars(self):
        """加载所有环境变量"""
        index = self.load_source_index()

        if not index:
            self.error("No config source index found, cannot load configuration")
            return

        categories = index.get('categories', {})

        # 定义优先级顺序（后加载的覆盖先加载的）
        priority_order = ['firebase', 'futu', 'telegram', 'database', 'agents']

        # 按优先级加载
        for category in priority_order:
            if category not in categories:
                continue

            category_info = categories[category]
            self.log(f"Loading category: {category}")

            env_vars = self.scan_category(category, category_info)

            for key, (value, source) in env_vars.items():
                self.env_vars[key] = value
                self.sources[key] = {
                    'source': source,
                    'category': category,
                    'loaded_at': datetime.now(timezone.utc).isoformat()
                }

        # 加载其他未在优先级列表中的分类
        for category, category_info in categories.items():
            if category in priority_order:
                continue

            self.log(f"Loading category: {category}")

            env_vars = self.scan_category(category, category_info)

            for key, (value, source) in env_vars.items():
                self.env_vars[key] = value
                self.sources[key] = {
                    'source': source,
                    'category': category,
                    'loaded_at': datetime.now(timezone.utc).isoformat()
                }

        self.log(f"Loaded {len(self.env_vars)} environment variables from {len(categories)} categories")

    def write_runtime_config(self):
        """写入运行时配置文件"""
        # 确保目录存在
        RUNTIME_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. 写入 .env 文件
        try:
            with open(RUNTIME_ENV_FILE, 'w') as f:
                f.write(f"# Auto-generated at: {timestamp}\n")
                f.write(f"# Source index: {self.source_index_path or PRIMARY_SOURCE_INDEX}\n")
                f.write(f"# Secret payload root: {SECRETS_ROOT}\n")
                f.write("# DO NOT EDIT MANUALLY - will be overwritten on restart\n\n")

                # 按分类分组写入
                by_category = defaultdict(list)
                for key, value in self.env_vars.items():
                    category = self.sources[key]['category']
                    by_category[category].append((key, value))

                for category in sorted(by_category.keys()):
                    f.write(f"# === {category.upper()} ===\n")
                    for key, value in sorted(by_category[category]):
                        f.write(f"{key}={value}\n")
                    f.write("\n")

            self.log(f"Written runtime .env: {RUNTIME_ENV_FILE}")

        except Exception as e:
            self.error(f"Failed to write .env file: {e}")

        # 2. 写入 sources.yaml
        try:
            with open(RUNTIME_SOURCES, 'w') as f:
                f.write(f"# Config Sources - Generated at {timestamp}\n\n")
                yaml.dump(self.sources, f, default_flow_style=False, allow_unicode=True)

            self.log(f"Written sources metadata: {RUNTIME_SOURCES}")

        except Exception as e:
            self.error(f"Failed to write sources.yaml: {e}")

        # 3. 写入时间戳
        try:
            with open(RUNTIME_TIMESTAMP, 'w') as f:
                f.write(f"{timestamp}\n")

            self.log(f"Written timestamp: {RUNTIME_TIMESTAMP}")

        except Exception as e:
            self.error(f"Failed to write timestamp: {e}")

    def write_audit_log(self):
        """写入审计日志"""
        RUNTIME_LOGS.mkdir(parents=True, exist_ok=True)

        audit_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'event': 'config_loaded',
            'source_index': str(self.source_index_path or PRIMARY_SOURCE_INDEX),
            'sources_count': len(set(s['source'] for s in self.sources.values())),
            'env_vars_count': len(self.env_vars),
            'conflicts': self.conflicts,
            'errors': self.errors
        }

        try:
            with open(AUDIT_LOG, 'a') as f:
                f.write(json.dumps(audit_entry) + '\n')

            self.log(f"Written audit log: {AUDIT_LOG}")

        except Exception as e:
            self.error(f"Failed to write audit log: {e}")

    def validate(self) -> bool:
        """验证配置完整性"""
        valid = True

        # 检查必需的环境变量（可根据需要扩展）
        required_vars = []  # 例如: ['TELEGRAM_BOT_TOKEN', 'POSTGRES_DSN']

        for var in required_vars:
            if var not in self.env_vars:
                self.error(f"Required environment variable missing: {var}")
                valid = False

        # 检查文件路径是否有效
        for key, value in self.env_vars.items():
            if 'PATH' in key and value.startswith('/'):
                path = Path(value)
                if not path.exists():
                    self.error(f"File path does not exist: {key}={value}")
                    valid = False

        return valid

    def reload(self) -> bool:
        """重新加载配置"""
        self.log("Starting configuration reload...")

        # 1. 加载所有环境变量
        self.load_all_env_vars()

        # 2. 验证配置
        if not self.validate():
            self.error("Configuration validation failed")
            # 继续执行，不中断

        # 3. 写入运行时配置
        self.write_runtime_config()

        # 4. 写入审计日志
        self.write_audit_log()

        # 5. 报告结果
        if self.errors:
            self.error(f"Configuration loaded with {len(self.errors)} errors")
            return False
        else:
            self.log("Configuration loaded successfully")
            return True


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description=(
            "环境变量配置加载器 - 从 /brain/infrastructure/config/runtime_env/index.yaml "
            "解析配置源并渲染到 /xkagent_infra/runtime/config/"
        )
    )
    parser.add_argument(
        '--reload',
        action='store_true',
        help="重新加载所有配置"
    )
    parser.add_argument(
        '--validate',
        action='store_true',
        help="仅验证配置完整性"
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help="静默模式（不打印日志）"
    )

    args = parser.parse_args()

    # 创建加载器
    loader = EnvVarsLoader(verbose=not args.quiet)

    # 执行操作
    if args.validate:
        loader.load_all_env_vars()
        if loader.validate():
            print("✅ Configuration validation passed")
            sys.exit(0)
        else:
            print("❌ Configuration validation failed")
            sys.exit(1)

    elif args.reload:
        success = loader.reload()
        sys.exit(0 if success else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
