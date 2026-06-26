import asyncio
import statistics
import time

from httpx import ASGITransport, AsyncClient

from app.main import app


async def run_once(client: AsyncClient) -> float:
    data = {
        "product_info": (
            "请估价：设备名称：气相色谱仪；品牌：Agilent；型号：8890；"
            "规格：FID检测器+自动进样器；用途：实验室检测。"
        )
    }
    started = time.perf_counter()
    resp = await client.post("/api/v1/chat/stream", data=data)
    cost = (time.perf_counter() - started) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"status={resp.status_code}, body={resp.text[:500]}")
    if "event: done" not in resp.text:
        raise RuntimeError("stream response missing done event")
    return cost


async def main(total: int = 5) -> None:
    transport = ASGITransport(app=app)
    costs = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for idx in range(total):
            c = await run_once(client)
            costs.append(c)
            print(f"run={idx + 1}, cost_ms={c:.2f}")
    print("----- summary -----")
    print(f"count={len(costs)}")
    print(f"avg_ms={statistics.mean(costs):.2f}")
    print(f"p50_ms={statistics.median(costs):.2f}")
    print(f"max_ms={max(costs):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
