from services.progress import Progress


async def test_reports_start_and_throttled_updates():
    updates = []

    async def record(done, total, seconds):
        updates.append((done, total, round(seconds, 2)))

    async def query():
        return "ok"

    progress = Progress(4, record, seconds_per_query=0.5, interval=0)
    await progress.start()
    results = [await progress.track(query()) for _ in range(4)]

    assert results == ["ok"] * 4
    assert updates[0] == (0, 4, 2.0)
    assert [done for done, _, _ in updates[1:]] == [1, 2, 3]


async def test_throttles_and_survives_callback_errors():
    calls = []

    async def failing(done, total, seconds):
        calls.append(done)
        raise RuntimeError("telegram down")

    async def query():
        return 1

    progress = Progress(3, failing, seconds_per_query=1, interval=60)
    await progress.start()
    for _ in range(3):
        await progress.track(query())
    assert calls == [0]
    assert progress.done == 3


async def test_estimate_is_smoothed_toward_measured_speed(monkeypatch):
    clock = iter([100.0, 110.0])  # created at t=100, one query done at t=110
    monkeypatch.setattr("services.progress.time.perf_counter", lambda: next(clock))
    reported = []

    async def record(done, total, seconds):
        reported.append(seconds)

    async def query():
        return None

    # Initial guess: 10 queries x 1s = finish at t=110. Measured: 10s per query, so 90s more.
    progress = Progress(10, record, seconds_per_query=1, interval=0)
    await progress.start()
    await progress.track(query())

    assert reported == [10.0, 45.0]  # finish averaged between t=110 and t=200, seen from t=110
