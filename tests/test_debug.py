"Cell debugging through a real ipykernel, on both transports: a breakpoint pauses the cell, the paused frame answers, and the cell finishes."
import asyncio, time
import pytest
from kunda.kernel import GatewayKernel, GatewayService, Kernel

WAIT = 90    # generous: the debugger's first start imports debugpy, and the test machine is often loaded

_gateway = None
def gateway():
    global _gateway
    if _gateway is None: _gateway = GatewayService(port=0).start()
    return _gateway

def teardown_module():
    if _gateway is not None: _gateway.stop()

async def started(transport, tmp_path):
    k = GatewayKernel(gateway(), cwd=str(tmp_path), inspect=False) if transport == 'gateway' else Kernel(cwd=str(tmp_path), inspect=False)
    return await asyncio.wait_for(k.start(), WAIT)

def bounded(coro): return asyncio.wait_for(coro, WAIT)

CELLS = [('c0', 'seed = 41'), ('c1', 'answer = seed + 1\nprint(answer)')]
both = pytest.mark.parametrize('transport', ['direct', 'gateway'])

@both
async def test_a_breakpoint_pauses_a_cell_whose_frame_answers_and_then_finishes(tmp_path, transport):
    "The stopped frame sees names an earlier cell made, its source maps back to its cell, and continuing finishes the run in the same kernel."
    k = await started(transport, tmp_path)
    cell = None
    try:
        assert (await bounded(k.execute(CELLS[0][1]))).ok
        code = CELLS[1][1]
        assert await bounded(k.debug_start(code, [1], notebook_cells=CELLS)) == [1]
        stopped = asyncio.Event()
        cell = asyncio.create_task(k.execute(code, timeout=WAIT, on_debug=lambda c: c.get('event') == 'stopped' and stopped.set()))
        await bounded(stopped.wait())
        state = await bounded(k.debug_state())
        assert state['paused'] and state['frames'], state
        assert k._debug_sources[state['frames'][0]['source']['path']] == 'c1'
        assert (await bounded(k.debug_evaluate('seed')))['result'] == '41'
        await bounded(k.debug_control('continue'))
        r = await bounded(cell)
        assert r.ok and r.text.strip() == '42', r
        assert (await bounded(k.execute('answer'))).text == '42'
        await bounded(k.debug_stop())
    finally:
        if cell is not None and not cell.done():
            cell.cancel()
            await asyncio.gather(cell, return_exceptions=True)
        await bounded(k.shutdown())

@both
async def test_a_rejected_debug_request_raises_and_the_debugger_still_answers(tmp_path, transport):
    "ipykernel answers a stack trace asked of a debugger nobody started with no success, which kunda raises; the lock is free afterwards."
    k = await started(transport, tmp_path)
    try:
        with pytest.raises(RuntimeError, match='rejected stackTrace'): await bounded(k.debug_request('stackTrace', {'threadId': 1}))
        assert await bounded(k.debug_start('x = 1', notebook_cells=[('c0', 'x = 1')])) == []
        await bounded(k.debug_stop())
    finally: await bounded(k.shutdown())

async def test_shutdown_settles_a_pending_gateway_debug_request(tmp_path):
    "An evaluate still running in the paused frame does not leave its caller waiting once the kernel goes."
    k = await started('gateway', tmp_path)
    cell = None
    try:
        code = 'import time\nx = 1'
        await bounded(k.debug_start(code, [2], notebook_cells=[('c0', code)]))
        stopped = asyncio.Event()
        cell = asyncio.create_task(k.execute(code, timeout=WAIT, on_debug=lambda c: c.get('event') == 'stopped' and stopped.set()))
        await bounded(stopped.wait())
        frame = (await bounded(k.debug_state()))['frame_id']
        slow = asyncio.create_task(k.debug_evaluate('time.sleep(60)', frame))
        await asyncio.sleep(1)
        assert not slow.done() and k._debug_pending is not None, 'the evaluate itself is in flight'
        t = time.monotonic()
        await bounded(k.shutdown())
        with pytest.raises(RuntimeError, match='not running'): await bounded(slow)
        assert time.monotonic() - t < 30
    finally:
        if cell is not None and not cell.done():
            cell.cancel()
            await asyncio.gather(cell, return_exceptions=True)
        await bounded(k.shutdown())
