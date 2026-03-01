#!/usr/bin/env python3
"""
IPC 消息统计
统计 IPC 消息的发送、接收和失败情况
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any
from collections import defaultdict


def scan_ipc_logs(log_dir: str = "/brain/runtime/logs/ipc", hours: int = 24) -> Dict[str, Any]:
    """扫描 IPC 日志文件，统计消息"""
    stats = {
        'total_messages': 0,
        'by_agent': defaultdict(lambda: {'sent': 0, 'received': 0}),
        'by_type': defaultdict(int),
        'by_priority': defaultdict(int),
        'failed': 0,
        'success': 0
    }

    if not os.path.exists(log_dir):
        return stats

    cutoff = datetime.now() - timedelta(hours=hours)

    try:
        for filename in os.listdir(log_dir):
            if not filename.endswith('.jsonl'):
                continue

            filepath = os.path.join(log_dir, filename)

            with open(filepath, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        msg = json.loads(line)

                        # 检查时间戳
                        ts = msg.get('ts', 0)
                        if ts < cutoff.timestamp():
                            continue

                        stats['total_messages'] += 1

                        # 统计发送者和接收者
                        from_agent = msg.get('from', 'unknown')
                        to_agent = msg.get('to', 'unknown')

                        stats['by_agent'][from_agent]['sent'] += 1
                        stats['by_agent'][to_agent]['received'] += 1

                        # 统计消息类型
                        msg_type = msg.get('message_type', 'unknown')
                        stats['by_type'][msg_type] += 1

                        # 统计优先级
                        priority = msg.get('priority', 'normal')
                        stats['by_priority'][priority] += 1

                        # 统计状态
                        status = msg.get('status', 'unknown')
                        if 'error' in status.lower() or 'fail' in status.lower():
                            stats['failed'] += 1
                        else:
                            stats['success'] += 1

                    except json.JSONDecodeError:
                        continue

    except Exception as e:
        print(f"Error scanning logs: {e}", file=sys.stderr)

    return stats


def format_stats(stats: Dict[str, Any], hours: int) -> str:
    """格式化统计输出"""
    output = []
    output.append(f"\n{'='*80}")
    output.append(f"IPC Message Statistics - Last {hours} hours")
    output.append(f"Report Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    output.append(f"{'='*80}\n")

    # 总体统计
    output.append(f"Total Messages: {stats['total_messages']}")
    output.append(f"  Success: {stats['success']} ({stats['success']/max(stats['total_messages'],1)*100:.1f}%)")
    output.append(f"  Failed:  {stats['failed']} ({stats['failed']/max(stats['total_messages'],1)*100:.1f}%)")
    output.append("")

    # 按消息类型统计
    if stats['by_type']:
        output.append("Messages by Type:")
        for msg_type, count in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
            output.append(f"  {msg_type:<15} {count:>5} ({count/stats['total_messages']*100:.1f}%)")
        output.append("")

    # 按优先级统计
    if stats['by_priority']:
        output.append("Messages by Priority:")
        for priority, count in sorted(stats['by_priority'].items(), key=lambda x: -x[1]):
            output.append(f"  {priority:<15} {count:>5} ({count/stats['total_messages']*100:.1f}%)")
        output.append("")

    # 按 Agent 统计（Top 10）
    if stats['by_agent']:
        output.append("Top Agents by Activity:")
        output.append(f"{'Agent':<40} {'Sent':>8} {'Received':>8} {'Total':>8}")
        output.append("-" * 80)

        agent_activity = []
        for agent, counts in stats['by_agent'].items():
            total = counts['sent'] + counts['received']
            agent_activity.append((agent, counts['sent'], counts['received'], total))

        for agent, sent, recv, total in sorted(agent_activity, key=lambda x: -x[3])[:10]:
            output.append(f"{agent:<40} {sent:>8} {recv:>8} {total:>8}")

    output.append("\n" + "="*80 + "\n")
    return "\n".join(output)


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='IPC Message Statistics')
    parser.add_argument('--hours', type=int, default=24, help='Time window in hours (default: 24)')
    parser.add_argument('--log-dir', type=str, default='/brain/runtime/logs/ipc', help='IPC log directory')

    args = parser.parse_args()

    stats = scan_ipc_logs(args.log_dir, args.hours)
    print(format_stats(stats, args.hours))


if __name__ == '__main__':
    main()
