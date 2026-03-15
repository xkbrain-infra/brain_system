#!/usr/bin/env python3
"""
定时任务监控
监控 Timer 服务的定时任务执行状态
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict


def scan_timer_logs(log_dir: str = "/xkagent_infra/runtime/logs/timer", hours: int = 24) -> Dict[str, Any]:
    """扫描 Timer 日志文件，统计任务执行"""
    stats = {
        'total_executions': 0,
        'by_task': defaultdict(lambda: {'success': 0, 'failed': 0, 'total': 0}),
        'success_rate': {},
        'recent_failures': []
    }

    if not os.path.exists(log_dir):
        return stats

    cutoff = datetime.now() - timedelta(hours=hours)

    try:
        for filename in os.listdir(log_dir):
            if not filename.endswith('.log') and not filename.endswith('.jsonl'):
                continue

            filepath = os.path.join(log_dir, filename)

            with open(filepath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue

                    # 尝试解析 JSON
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        # 如果不是 JSON，尝试从文本日志提取
                        if 'task' in line.lower() and ('executed' in line.lower() or 'failed' in line.lower()):
                            continue
                        else:
                            continue

                    # 检查时间戳
                    ts = entry.get('timestamp', entry.get('ts', 0))
                    if isinstance(ts, str):
                        try:
                            ts = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
                        except:
                            continue

                    if ts < cutoff.timestamp():
                        continue

                    stats['total_executions'] += 1

                    # 统计任务
                    task_name = entry.get('task_name', entry.get('task', 'unknown'))
                    status = entry.get('status', 'unknown')

                    stats['by_task'][task_name]['total'] += 1

                    if status == 'success' or 'success' in status.lower():
                        stats['by_task'][task_name]['success'] += 1
                    elif status == 'failed' or 'error' in status.lower() or 'fail' in status.lower():
                        stats['by_task'][task_name]['failed'] += 1

                        # 记录最近的失败
                        if len(stats['recent_failures']) < 10:
                            stats['recent_failures'].append({
                                'task': task_name,
                                'time': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S'),
                                'error': entry.get('error', 'Unknown error')
                            })

    except Exception as e:
        print(f"Error scanning logs: {e}", file=sys.stderr)

    # 计算成功率
    for task, counts in stats['by_task'].items():
        if counts['total'] > 0:
            stats['success_rate'][task] = counts['success'] / counts['total'] * 100

    return stats


def format_task_stats(stats: Dict[str, Any], hours: int) -> str:
    """格式化任务统计输出"""
    output = []
    output.append(f"\n{'='*80}")
    output.append(f"Task Execution Monitor - Last {hours} hours")
    output.append(f"Report Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"{'='*80}\n")

    # 总体统计
    output.append(f"Total Executions: {stats['total_executions']}")
    output.append(f"Unique Tasks: {len(stats['by_task'])}")
    output.append("")

    # 按任务统计
    if stats['by_task']:
        output.append("Task Execution Summary:")
        output.append(f"{'Task Name':<40} {'Success':>8} {'Failed':>8} {'Rate':>8}")
        output.append("-" * 80)

        for task, counts in sorted(stats['by_task'].items(), key=lambda x: -x[1]['total']):
            success = counts['success']
            failed = counts['failed']
            rate = stats['success_rate'].get(task, 0)

            output.append(f"{task:<40} {success:>8} {failed:>8} {rate:>7.1f}%")

        output.append("")

    # 最近的失败
    if stats['recent_failures']:
        output.append("Recent Failures:")
        for failure in stats['recent_failures']:
            output.append(f"  [{failure['time']}] {failure['task']}")
            output.append(f"    Error: {failure['error']}")
        output.append("")

    output.append("="*80 + "\n")
    return "\n".join(output)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Task Execution Monitor')
    parser.add_argument('--hours', type=int, default=24, help='Time window in hours (default: 24)')
    parser.add_argument('--log-dir', type=str, default='/xkagent_infra/runtime/logs/timer', help='Timer log directory')

    args = parser.parse_args()

    stats = scan_timer_logs(args.log_dir, args.hours)
    print(format_task_stats(stats, args.hours))


if __name__ == '__main__':
    main()
