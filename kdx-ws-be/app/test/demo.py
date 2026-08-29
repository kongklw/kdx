import asyncio
import time

# 模拟异步获取数据的协程
async def fetch_data(url, delay):
    print(f"开始从 {url} 获取数据...")
    # 模拟网络延迟
    await asyncio.sleep(delay)
    print(f"完成从 {url} 获取数据。")
    return f"数据来自 {url}"

# 另一个协程，用于展示如何同时运行多个协程
async def main():
    # 定义要获取数据的网站和对应的延迟
    sites = [
        ("网站A", 2),
        ("网站B", 1),
        ("网站C", 3)
    ]

    # 创建任务列表
    tasks = []
    for site, delay in sites:
        task = asyncio.create_task(fetch_data(site, delay))  # 创建任务
        tasks.append(task)

    # 等待所有任务完成并获取结果
    results = await asyncio.gather(*tasks)

    # 打印结果
    for result in results:
        print(result)

    # 下面展示 Future 对象的简单使用（这里通过 ensure_future 创建任务，返回的就是 Future 对象相关任务）
    # 创建一个 Future 对象相关的任务（在较新版本中 create_task 更常用，ensure_future 兼容性更好）
    future_task = asyncio.ensure_future(fetch_data("额外网站", 1.5))
    await future_task
    print(f"Future 任务结果: {future_task.result()}")

# 获取事件循环并运行主协程
if __name__ == "__main__":
    start_time = time.time()
    asyncio.run(main())  # asyncio.run 会自动管理事件循环
    end_time = time.time()
    print(f"总耗时: {end_time - start_time} 秒")
