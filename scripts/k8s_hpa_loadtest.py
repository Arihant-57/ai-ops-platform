"""
Concurrent load generator for Kubernetes HPA evaluation against ai-ops-platform.
Prints per-window latency and throughput alongside the final summary so live
scaling improvements can be observed as HPA adds replicas.
"""
import argparse
import asyncio
import time
import httpx


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8001")
    p.add_argument("--concurrency", type=int, default=48)
    p.add_argument("--duration", type=int, default=75)
    p.add_argument("--interval", type=int, default=15)
    args = p.parse_args()

    all_lat: list[float] = []
    win_lat: list[float] = []
    ok = 0
    err = 0
    win_ok = 0
    win_err = 0
    last_err = ""
    stop_at = time.perf_counter() + args.duration
    t_start = time.perf_counter()

    async def worker(wid: int) -> None:
        nonlocal ok, err, win_ok, win_err, last_err
        limits = httpx.Limits(max_keepalive_connections=0)
        async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
            i = 0
            while time.perf_counter() < stop_at:
                aid = 7 + ((wid + i) % 3)
                i += 1
                t0 = time.perf_counter()
                try:
                    r = await client.post(
                        f"{args.url}/agents/{aid}/run",
                        json={
                            "prompt": "Analyze Kubernetes HPA scaling latency.",
                            "source": "loadtest",
                            "simulate_failures": False,
                        },
                    )
                    ms = (time.perf_counter() - t0) * 1000
                    if r.status_code in (200, 201):
                        ok += 1
                        win_ok += 1
                        all_lat.append(ms)
                        win_lat.append(ms)
                    else:
                        err += 1
                        win_err += 1
                        last_err = f"HTTP {r.status_code}"
                except Exception as exc:
                    err += 1
                    win_err += 1
                    last_err = str(exc)

    async def reporter() -> None:
        nonlocal win_lat, win_ok, win_err
        while time.perf_counter() < stop_at:
            await asyncio.sleep(args.interval)
            snap_lat = sorted(win_lat)
            s_ok, s_err = win_ok, win_err
            win_lat = []
            win_ok = 0
            win_err = 0
            elapsed = time.perf_counter() - t_start
            avg = sum(snap_lat) / len(snap_lat) if snap_lat else 0.0
            p95 = snap_lat[min(len(snap_lat) - 1, int(0.95 * len(snap_lat)))] if snap_lat else 0.0
            print(
                f"[t={elapsed:4.0f}s] ok={s_ok:4d} err={s_err} "
                f"rps={s_ok / args.interval:5.1f} avg_ms={avg:5.1f} p95_ms={p95:5.1f}",
                flush=True,
            )

    await asyncio.gather(*[worker(w) for w in range(args.concurrency)], reporter())
    elapsed = time.perf_counter() - t_start
    all_lat.sort()
    avg = sum(all_lat) / len(all_lat) if all_lat else 0.0
    p95 = all_lat[min(len(all_lat) - 1, int(0.95 * len(all_lat)))] if all_lat else 0.0
    print(
        f"LOAD_SUMMARY duration_s={elapsed:.1f} concurrency={args.concurrency} "
        f"ok={ok} err={err} avg_ms={avg:.1f} p95_ms={p95:.1f} rps={ok/elapsed:.1f} last_err={last_err!r}"
    )


if __name__ == "__main__":
    asyncio.run(main())
