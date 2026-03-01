"""
BS-025-MOD-state-store: State Store
YAML 原子写持久化 + runtime_state.json 去重状态管理
"""
import glob
import json
import logging
import os
from typing import Any, Dict, Optional, Set

import yaml

logger = logging.getLogger(__name__)


def cleanup_tmp_files(directory: str) -> int:
    """清理启动时残留的 *.yaml.tmp 文件，返回清理数量。"""
    pattern = os.path.join(directory, "**", "*.yaml.tmp")
    tmp_files = glob.glob(pattern, recursive=True)
    count = 0
    for f in tmp_files:
        try:
            os.remove(f)
            logger.info(f"Cleaned up tmp file: {f}")
            count += 1
        except OSError as e:
            logger.warning(f"Failed to remove tmp file {f}: {e}")
    return count


def read_project_state(yaml_path: str) -> Optional[Dict[str, Any]]:
    """读取项目 task_manager.yaml，返回 dict；文件不存在或解析失败返回 None。"""
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data
    except FileNotFoundError:
        logger.warning(f"State file not found: {yaml_path}")
        return None
    except yaml.YAMLError as e:
        logger.error(f"YAML parse error in {yaml_path}: {e}")
        return None


def write_project_state(yaml_path: str, data: Dict[str, Any]) -> bool:
    """
    原子写入 YAML：先写 .tmp 文件，再用 os.replace() 替换目标文件。
    保证 crash 安全：replace 是 POSIX 原子操作，中途 crash 只留 .tmp。
    返回 True 表示成功，False 表示失败（旧文件保持完整）。
    """
    tmp_path = yaml_path + ".tmp"
    try:
        content = yaml.dump(
            data, allow_unicode=True, default_flow_style=False, sort_keys=False
        )
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, yaml_path)
        logger.debug(f"State written atomically: {yaml_path}")
        return True
    except OSError as e:
        logger.error(f"Failed to write state to {yaml_path}: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False


class RuntimeState:
    """
    runtime_state.json 的读写封装。
    持久化 processed_msg_ids（IPC 去重）、last_scan_time、last_shutdown_time。
    """

    _DEFAULT: Dict[str, Any] = {
        "processed_msg_ids": [],
        "last_scan_time": None,
        "last_shutdown_time": None,
    }

    def __init__(self, json_path: str):
        self.json_path = json_path
        self._data: Dict[str, Any] = {}
        self._processed_msg_ids: Set[str] = set()

    def load(self) -> None:
        """从 json_path 加载，文件不存在则使用默认值，解析失败则重置。"""
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._processed_msg_ids = set(self._data.get("processed_msg_ids", []))
            logger.info(
                f"Runtime state loaded: {len(self._processed_msg_ids)} processed msg_ids"
            )
        except FileNotFoundError:
            self._data = dict(self._DEFAULT)
            self._processed_msg_ids = set()
            logger.info("No runtime_state.json found, starting fresh")
        except json.JSONDecodeError as e:
            logger.error(f"runtime_state.json parse error: {e}, resetting to default")
            self._data = dict(self._DEFAULT)
            self._processed_msg_ids = set()

    def save(self) -> bool:
        """原子写入 json_path（.tmp → os.replace），返回是否成功。"""
        self._data["processed_msg_ids"] = list(self._processed_msg_ids)
        tmp_path = self.json_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.json_path)
            return True
        except OSError as e:
            logger.error(f"Failed to write runtime_state.json: {e}")
            return False

    def is_processed(self, msg_id: str) -> bool:
        """判断 msg_id 是否已处理（幂等去重）。"""
        return msg_id in self._processed_msg_ids

    def mark_processed(self, msg_id: str) -> None:
        """标记 msg_id 为已处理（内存更新，调用 save() 才持久化）。"""
        self._processed_msg_ids.add(msg_id)

    def set_last_scan_time(self, ts: str) -> None:
        self._data["last_scan_time"] = ts

    def set_last_shutdown_time(self, ts: str) -> None:
        self._data["last_shutdown_time"] = ts

    @property
    def processed_msg_ids(self) -> Set[str]:
        return frozenset(self._processed_msg_ids)
