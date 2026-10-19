"One kernel per key, and a policy for how many stay alight."
import asyncio, threading, time
import pytest
from kunda.pool import IDLE_SECONDS, KernelLimit, KernelPool, RuntimeBroker

async def test_one_key_gets_one_kernel_however_many_ask(tmp_path):
    """Two browser panels open the same notebook at once. Starting a kernel twice would leave one
    orphaned with nobody holding it, and the namespace would depend on which reply won."""
    pool = KernelPool(idle=0)
    try:
        a, b = await asyncio.gather(pool.get('nb', cwd=str(tmp_path), inspect=False),
                                    pool.get('nb', cwd=str(tmp_path), inspect=False))
        assert a is b and a.alive
        assert (await a.execute('1+1')).ok
        assert pool.peek('nb') is a
    finally: await pool.close_all()

async def test_different_keys_get_different_kernels(tmp_path):
    "Two notebooks are two namespaces; that is the whole point of keying the pool."
    pool = KernelPool(idle=0)
    try:
        a = await pool.get('one', cwd=str(tmp_path), inspect=False)
        b = await pool.get('two', cwd=str(tmp_path), inspect=False)
        assert a is not b
        await a.execute('mine = 1')
        assert not (await b.execute('mine')).ok, 'and neither can see the other'
    finally: await pool.close_all()

async def test_a_kernel_that_failed_to_start_is_not_left_in_the_pool(tmp_path):
    "A dead entry would be handed to the next caller, which then fails for a reason long past."
    pool = KernelPool(idle=0)
    try:
        with pytest.raises(Exception):
            await pool.get('bad', cwd=str(tmp_path), python='/definitely/not/a/python', inspect=False)
        assert pool.peek('bad') is None and 'bad' not in pool.kernels
    finally: await pool.close_all()

async def test_peek_never_hands_back_something_still_starting(tmp_path):
    "`peek` is for callers that must not wait; a half-started kernel is not a kernel yet."
    pool = KernelPool(idle=0)
    try:
        task = asyncio.create_task(pool.get('nb', cwd=str(tmp_path), inspect=False))
        await asyncio.sleep(0)
        assert pool.peek('nb') is None
        await task
        assert pool.peek('nb') is not None
    finally: await pool.close_all()

async def test_closing_one_leaves_the_others_alone(tmp_path):
    pool = KernelPool(idle=0)
    try:
        a = await pool.get('one', cwd=str(tmp_path), inspect=False)
        b = await pool.get('two', cwd=str(tmp_path), inspect=False)
        await pool.close('one')
        assert not a.alive and b.alive and pool.peek('two') is b
    finally: await pool.close_all()

def test_choose_sets_the_next_kernel_and_leaves_running_ones_alone():
    pool = KernelPool(idle=0)
    assert pool.choose(kernel='ipymini')['kernel'] == 'ipymini'
    assert pool.choose(kernel='nonsense')['kernel'] == 'ipymini', 'an unknown name changes nothing'
    assert pool.choose(python='/some/python')['python'] == '/some/python'
    assert pool.choose()['python'] == '/some/python', 'and not passing it is not clearing it'

def test_a_broker_keeps_the_limit_and_names_what_it_would_close():
    """At the limit the person is told which kernel would go, not shown a failure: the alternative
    is a notebook that will not open with no way to learn why."""
    b = RuntimeBroker(max_kernels=1, auto_manage=False)
    pool = KernelPool(idle=0, broker=b)
    assert pool.broker is b and b.pools == [pool], 'registering is two-way'
    st = b.status()
    assert st['limit'] == 1 and st['live'] == 0 and st['runtimes'] == []
    assert b.stalest() is None, 'nothing is running, so nothing is the stalest'
    assert b._candidate() is None

async def test_the_reaper_takes_nothing_when_it_is_switched_off(tmp_path):
    "`idle=0` is how a host says never: a sweep that fired anyway would close a live namespace."
    pool = KernelPool(idle=0)
    try:
        await pool.get('nb', cwd=str(tmp_path), inspect=False)
        assert await pool.reap() == []
    finally: await pool.close_all()

def test_the_limit_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv('KUNDA_MAX_KERNELS', '3')
    assert RuntimeBroker().max_kernels == 3
    monkeypatch.setenv('KUNDA_KERNEL_AUTO', 'yes')
    assert RuntimeBroker().auto_manage is True

def test_the_default_idle_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv('KUNDA_KERNEL_IDLE', '7')
    assert KernelPool().idle == 7
    monkeypatch.delenv('KUNDA_KERNEL_IDLE')
    assert KernelPool().idle == IDLE_SECONDS

def test_a_language_with_no_jupyter_kernel_reaches_the_hosts_own_runner():
    "kunda knows Jupyter kernels. Anything else is the host's, passed in rather than imported."
    class Runner: wants_key = True
    pool = KernelPool(runner_for=lambda lang: Runner if lang == 'rust' else None)
    assert pool._class_for({'lang': 'rust'}) is Runner
    assert pool._class_for({'lang': 'python'}).__name__ == 'Kernel'

def test_without_a_runner_hook_an_unknown_language_still_resolves_to_a_kernel():
    "So the failure comes from `installed_spec`, which names what would install one."
    assert KernelPool()._class_for({'lang': 'brainfuck'}).__name__ == 'Kernel'

def _stub(hang=0, nap=0):
    "A stand-in kernel. The first `hang` starts never finish; a shutdown takes `nap` seconds."
    class Stub:
        wants_key, made, started, closing = True, [], threading.Event(), threading.Event()
        def __init__(self, port=None, key=None, **kw):
            self.key, self.alive, self.busy, self.idle_for, self.pid = key, False, False, 5, None
            self.kernel_kind, self.cwd, self.evicted = 'stub', None, None
            Stub.made.append(self)
        def touch(self): return self
        async def start(self):
            if len(Stub.made) <= hang: Stub.started.set(); await asyncio.Event().wait()
            self.alive = True
            return self
        async def shutdown(self):
            Stub.closing.set()
            await asyncio.sleep(nap)
            self.alive = False
    return Stub

def _loop_thread():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread

def _stop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)

def test_a_start_stranded_on_a_stopped_loop_is_replaced():
    """A canvas runtime times out a start and closes, stopping its loop with the start pending. The next
    loop must not wait on that dead task, and the slot it held must not count against the limit."""
    Stub = _stub(hang=1)
    broker = RuntimeBroker(max_kernels=1, auto_manage=False)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Stub)
    loop, thread = _loop_thread()
    try:
        asyncio.run_coroutine_threadsafe(pool.get('nb', lang='stub'), loop)
        assert Stub.started.wait(5)
        _stop(loop, thread)
        k = asyncio.run(asyncio.wait_for(pool.get('nb', lang='stub'), 5))
        assert k.alive and k is Stub.made[1] and pool.kernels == {'nb': k}
        assert not broker._reserved and not pool._starting
    finally: loop.close()

async def test_a_start_every_caller_gave_up_on_still_cleans_up():
    """Callers bound their wait. A start that finished after every one of them had timed out stayed in
    `_starting` with its slot reserved, so each later `get` got back its old result or its old error."""
    class Slow:
        wants_key, made = True, []
        def __init__(self, port=None, key=None, **kw):
            self.key, self.alive, self.busy, self.idle_for, self.pid = key, False, False, 5, None
            self.kernel_kind, self.cwd, self.evicted = 'stub', None, None
            Slow.made.append(self)
        def touch(self): return self
        async def start(self):
            await asyncio.sleep(.2)
            if len(Slow.made) == 1: raise RuntimeError('the first start fails')
            self.alive = True
            return self
        async def shutdown(self): self.alive = False
    broker = RuntimeBroker(max_kernels=2, auto_manage=False)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Slow)
    with pytest.raises(TimeoutError): await asyncio.wait_for(pool.get('nb', lang='stub'), .05)
    await asyncio.sleep(.4)
    assert not pool._starting and not broker._reserved
    k = await asyncio.wait_for(pool.get('nb', lang='stub'), 5)
    assert k.alive and k is Slow.made[1]

def test_a_stranded_start_that_finishes_late_leaves_the_new_reservation_alone():
    "A start dropped as stranded, then finished when its loop ran again, gave back the slot its successor held."
    Stub, go = _stub(), None
    class Late(Stub):
        async def start(self):
            nonlocal go
            if len(Stub.made) == 1:
                go = asyncio.Event(); Stub.started.set(); await go.wait()
            self.alive = True
            return self
    broker = RuntimeBroker(max_kernels=2, auto_manage=False)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Late)
    loop, thread = _loop_thread()
    try:
        asyncio.run_coroutine_threadsafe(pool.get('nb', lang='stub'), loop)
        assert Stub.started.wait(5)
        _stop(loop, thread)
        async def reserve_again():
            pool._strand()
            await broker.admit(pool, 'nb')
        asyncio.run(reserve_again())
        held = set(broker._reserved)
        thread = threading.Thread(target=loop.run_forever, daemon=True); thread.start()
        loop.call_soon_threadsafe(go.set)
        time.sleep(.3)
        assert broker._reserved == held, 'the stale start released a slot it no longer owned'
    finally:
        _stop(loop, thread); loop.close()

def test_a_stranded_start_does_not_hold_a_slot_for_other_keys():
    "The limit is one: a start that can never finish must not keep every other notebook out."
    Stub = _stub(hang=1)
    broker = RuntimeBroker(max_kernels=1, auto_manage=False)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Stub)
    loop, thread = _loop_thread()
    try:
        asyncio.run_coroutine_threadsafe(pool.get('nb', lang='stub'), loop)
        assert Stub.started.wait(5)
        _stop(loop, thread)
        k = asyncio.run(asyncio.wait_for(pool.get('other', lang='stub'), 5))
        assert k.alive and list(pool.kernels) == ['other'] and not broker._reserved
    finally: loop.close()

def test_a_sweep_on_a_stopped_loop_is_started_again():
    "An idle sweep that lived on a stopped loop is never done, so it was never replaced."
    Stub = _stub()
    pool = KernelPool(idle=60, runner_for=lambda lang: Stub)
    loop, thread = _loop_thread()
    try:
        asyncio.run_coroutine_threadsafe(pool.get('nb', lang='stub'), loop).result(5)
        first = pool._sweep
        _stop(loop, thread)
        async def again():
            await pool.get('nb', lang='stub')
            return pool._sweep is not first and pool._sweep.get_loop() is asyncio.get_running_loop()
        assert asyncio.run(asyncio.wait_for(again(), 5))
    finally: loop.close()

def test_the_broker_serves_contenders_from_two_loops():
    """Eviction is slow and awaited, so another loop's admit or release meets it. An asyncio.Lock binds to
    the first loop that contends and refuses the next."""
    Stub = _stub(nap=1)
    broker = RuntimeBroker(max_kernels=1, auto_manage=True)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Stub)
    old = pool.kernels['old'] = Stub(key='old')
    old.alive = True
    loop, thread = _loop_thread()
    try:
        async def both(): return await asyncio.gather(broker.admit(pool, 'new'), broker.release(pool, 'x'))
        fut = asyncio.run_coroutine_threadsafe(both(), loop)
        assert Stub.closing.wait(5)
        asyncio.run(asyncio.wait_for(broker.release(pool, 'y'), 5))
        evicted, _ = fut.result(5)
        assert evicted['key'] == 'old' and not old.alive and 'old' not in pool.kernels
        assert broker._reserved == {(id(pool), 'new')}
    finally: _stop(loop, thread); loop.close()

async def test_the_limit_is_still_checked_atomically_while_a_victim_closes():
    "Two keys ask at the limit with one idle victim: one gets the slot, the other is refused, never both."
    Stub = _stub(nap=0.2)
    broker = RuntimeBroker(max_kernels=1, auto_manage=True)
    pool = KernelPool(idle=0, broker=broker, runner_for=lambda lang: Stub)
    old = pool.kernels['old'] = Stub(key='old')
    old.alive = True
    rows = await asyncio.gather(broker.admit(pool, 'a'), broker.admit(pool, 'b'), return_exceptions=True)
    assert sum(isinstance(r, KernelLimit) for r in rows) == 1 and sum(isinstance(r, dict) for r in rows) == 1
    assert len(broker._reserved) == 1 and not old.alive
