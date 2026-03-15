#!/usr/bin/env python3
"""Performance test for /api/system/status endpoint.

Target: p99 < 500ms @ 10 QPS for 60 seconds.
"""

import asyncio
import time
from statistics import mean, stdev
from typing import List

import httpx


async def make_request(client: httpx.AsyncClient, url: str) -> float:
    """Make a single request and return elapsed time in ms."""
    start = time.time()
    try:
        response = await client.get(url, timeout=2.0)
        elapsed_ms = (time.time() - start) * 1000.0

        if response.status_code != 200:
            print(f"⚠️ Non-200 status: {response.status_code}")

        return elapsed_ms
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000.0
        print(f"❌ Request failed: {e}")
        return elapsed_ms


async def run_load_test(url: str, qps: int = 10, duration_seconds: int = 60) -> dict:
    """Run load test at specified QPS for given duration.

    Args:
        url: Target URL
        qps: Queries per second
        duration_seconds: Test duration in seconds

    Returns:
        dict with latencies and statistics
    """
    interval = 1.0 / qps  # Time between requests
    latencies: List[float] = []

    print(f"🚀 Starting load test:")
    print(f"   URL: {url}")
    print(f"   QPS: {qps}")
    print(f"   Duration: {duration_seconds}s")
    print(f"   Total requests: {qps * duration_seconds}")
    print()

    async with httpx.AsyncClient() as client:
        start_time = time.time()
        end_time = start_time + duration_seconds
        request_count = 0

        while time.time() < end_time:
            request_start = time.time()

            # Make request
            latency = await make_request(client, url)
            latencies.append(latency)
            request_count += 1

            # Progress update every 10 seconds
            if request_count % (qps * 10) == 0:
                elapsed = time.time() - start_time
                print(f"⏱️  {elapsed:.0f}s: {request_count} requests, "
                      f"avg {mean(latencies[-qps*10:]):.1f}ms")

            # Sleep to maintain QPS rate
            elapsed = time.time() - request_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    total_elapsed = time.time() - start_time

    # Calculate statistics
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    p50 = latencies_sorted[int(n * 0.50)] if n > 0 else 0
    p95 = latencies_sorted[int(n * 0.95)] if n > 0 else 0
    p99 = latencies_sorted[int(n * 0.99)] if n > 0 else 0

    return {
        "total_requests": request_count,
        "duration_seconds": total_elapsed,
        "actual_qps": request_count / total_elapsed,
        "latencies": latencies,
        "stats": {
            "min": min(latencies) if latencies else 0,
            "max": max(latencies) if latencies else 0,
            "mean": mean(latencies) if latencies else 0,
            "stdev": stdev(latencies) if len(latencies) > 1 else 0,
            "p50": p50,
            "p95": p95,
            "p99": p99,
        }
    }


def print_results(results: dict, target_p99: float = 500.0):
    """Print test results."""
    stats = results["stats"]

    print()
    print("=" * 60)
    print("📊 PERFORMANCE TEST RESULTS")
    print("=" * 60)
    print(f"Total Requests: {results['total_requests']}")
    print(f"Duration: {results['duration_seconds']:.2f}s")
    print(f"Actual QPS: {results['actual_qps']:.2f}")
    print()
    print("Latency Statistics (ms):")
    print(f"  Min:    {stats['min']:.2f}")
    print(f"  Mean:   {stats['mean']:.2f}")
    print(f"  Stdev:  {stats['stdev']:.2f}")
    print(f"  p50:    {stats['p50']:.2f}")
    print(f"  p95:    {stats['p95']:.2f}")
    print(f"  p99:    {stats['p99']:.2f}")
    print(f"  Max:    {stats['max']:.2f}")
    print()

    # Check target
    if stats['p99'] < target_p99:
        print(f"✅ PASS: p99 {stats['p99']:.2f}ms < {target_p99}ms")
    else:
        print(f"❌ FAIL: p99 {stats['p99']:.2f}ms >= {target_p99}ms")

    print("=" * 60)


async def main():
    """Main entry point."""
    url = "http://127.0.0.1:9000/api/system/status"
    qps = 10
    duration = 60
    target_p99 = 500.0

    # Run test
    results = await run_load_test(url, qps, duration)

    # Print results
    print_results(results, target_p99)

    # Save detailed results
    output_file = "/tmp/system_status_perf_results.txt"
    with open(output_file, "w") as f:
        f.write(f"Performance Test Results\n")
        f.write(f"========================\n\n")
        f.write(f"Total Requests: {results['total_requests']}\n")
        f.write(f"Duration: {results['duration_seconds']:.2f}s\n")
        f.write(f"Actual QPS: {results['actual_qps']:.2f}\n\n")
        f.write(f"Latency Statistics (ms):\n")
        for key, value in results['stats'].items():
            f.write(f"  {key}: {value:.2f}\n")
        f.write(f"\nTarget: p99 < {target_p99}ms\n")
        f.write(f"Result: {'PASS' if results['stats']['p99'] < target_p99 else 'FAIL'}\n")

    print(f"\n📝 Detailed results saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
