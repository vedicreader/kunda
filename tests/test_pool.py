"One kernel per key, and a policy for how many stay alight."
import asyncio
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
