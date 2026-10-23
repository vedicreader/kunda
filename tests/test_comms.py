"Widget comms through a real ipykernel: kunda is the only reader of each kernel's messages, on both transports."
import asyncio, time
import pytest
from kunda import kernel as kmod
from kunda.kernel import GatewayKernel, GatewayService, Kernel
from kunda.pool import KernelPool

_gateway = None
def gateway():
    global _gateway
    if _gateway is None: _gateway = GatewayService(port=0).start()
    return _gateway

def teardown_module():
    if _gateway is not None: _gateway.stop()

async def started(transport, tmp_path):
    k = GatewayKernel(gateway(), cwd=str(tmp_path), inspect=False) if transport == 'gateway' else Kernel(cwd=str(tmp_path), inspect=False)
    return await k.start()

async def until(pred, timeout=15):
    "The first truthy `pred()`, polled; the test fails when it never comes."
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (r := pred()): return r
        await asyncio.sleep(.05)
    raise AssertionError('condition never held')

def of(seen, msg_type, pred=lambda m: True):
    return lambda: next((m for m in seen if m.get('msg_type') == msg_type and pred(m)), None)

ECHO = r'''from ipykernel.comm import Comm
c = Comm(target_name='kunda.test', data={'hi': 1}, buffers=[b'\x00\x01'])
@c.on_msg
def _echo(msg):
    d = msg['content']['data']
    if d.get('say'): print(d['say'])
    c.send({'echo': d, 'cell_done': globals().get('cell_done', False)}, buffers=msg['buffers'])
'''

both = pytest.mark.parametrize('transport', ['direct', 'gateway'])

@both
async def test_a_comm_reaches_subscribers_and_kunda_can_answer_it(tmp_path, transport):
    "A comm opened by a cell, and the kernel's answer to kunda's `comm_send` outside any run, both reach a subscriber with buffers."
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        assert (await k.execute(ECHO)).ok
        opened = await until(of(seen, 'comm_open'))
        assert opened['content']['target_name'] == 'kunda.test' and opened['buffers'] == [b'\x00\x01']
        assert opened['header'] and opened['parent_header'] and 'metadata' in opened
        cid = opened['content']['comm_id']
        k.comm_send(cid, {'n': 2}, buffers=[b'zz'])
        echo = await until(of(seen, 'comm_msg', lambda m: m['content']['data'].get('echo') == {'n': 2}))
        assert echo['buffers'] == [b'zz']
    finally: await k.shutdown()

@both
async def test_a_comm_message_sent_during_a_cell_is_handled_after_it(tmp_path, transport):
    "`comm_send` returns at once while a cell sleeps; the kernel handles the message once the cell is done."
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        await k.execute(ECHO)
        cid = (await until(of(seen, 'comm_open')))['content']['comm_id']
        cell = asyncio.create_task(k.execute('import time; time.sleep(3); cell_done = True'))
        await asyncio.sleep(.5)
        k.comm_send(cid, {'during': True})
        assert not cell.done(), 'sent while the cell was still running'
        assert (await cell).ok
        echo = await until(of(seen, 'comm_msg', lambda m: m['content']['data'].get('echo') == {'during': True}))
        assert echo['content']['data']['cell_done'] is True, 'handled only after the cell finished'
    finally: await k.shutdown()

@both
async def test_comm_info_and_complete_overlap_a_running_cell(tmp_path, transport):
    k = await started(transport, tmp_path)
    try:
        await k.execute(ECHO)
        cell = asyncio.create_task(k.execute('import time; time.sleep(1); 7'))
        await asyncio.sleep(.3)
        info, comp = await asyncio.gather(k.comm_info(), k.complete('pri', 3))
        run = await cell
        assert run.ok and '7' in run.text
        assert info['status'] == 'ok' and any(v.get('target_name') == 'kunda.test' for v in info['comms'].values())
        assert 'print' in comp['matches']
        assert (await k.comm_info('no.such.target'))['comms'] == {}
    finally: await k.shutdown()

@both
async def test_output_from_a_comm_handler_goes_to_subscribers_not_to_a_run(tmp_path, transport):
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        last = await k.execute(ECHO)
        cid = (await until(of(seen, 'comm_open')))['content']['comm_id']
        k.comm_send(cid, {'say': 'from the handler'})
        nxt = await k.execute('1')                 # running while the kernel handles the message queued ahead of it
        out = await until(of(seen, 'stream', lambda m: 'from the handler' in m['content']['text']))
        assert out['parent_header']['msg_type'] == 'comm_msg'
        assert 'from the handler' not in last.text + nxt.text
    finally: await k.shutdown()

OUTPUT = r'''import ipywidgets as w
from IPython.display import clear_output
out = w.Output()
display(out)
with out:
    print('first')
    clear_output()
    print('second')
print('in the cell')
'''

@both
async def test_an_output_widget_captures_its_own_output(tmp_path, transport):
    "`with out:` output reaches subscribers tagged with the widget; the cell keeps one widget view and its own print."
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        r = await k.execute(OUTPUT)
        assert r.ok, r.error
        views = [o for o in r.outputs if 'application/vnd.jupyter.widget-view+json' in o.get('data', {})]
        assert len(views) == 1, r.outputs
        model = views[0]['data']['application/vnd.jupyter.widget-view+json']['model_id']
        assert [o['text'] for o in r.outputs if o['output_type'] == 'stream'] == ['in the cell\n'], r.outputs
        await until(of(seen, 'stream', lambda m: 'second' in m['content']['text']))
        captured = [m for m in seen if m.get('output_comm_id') == model]
        assert [m['msg_type'] for m in captured] == ['stream', 'clear_output', 'stream'], captured
        assert not any('in the cell' in m['content'].get('text', '') for m in seen if m['msg_type'] == 'stream')
    finally: await k.shutdown()

async def test_a_dropped_gateway_socket_settles_the_run_and_the_router_keeps_going(tmp_path, monkeypatch):
    "jupygate drops frames in flight when the websocket dies; the run settles, and comm traffic flows afterwards."
    monkeypatch.setattr(kmod, 'QUIET', .5)
    k, seen = await started('gateway', tmp_path), []
    try:
        k.subscribe(seen.append)
        await k.execute(ECHO)
        cid = (await until(of(seen, 'comm_open')))['content']['comm_id']
        cell = asyncio.create_task(k.execute('import time; time.sleep(2); y = 2', timeout=60))
        await asyncio.sleep(1); k.kc._ws.transport.pause_reading()
        await asyncio.sleep(2.5); k.kc._ws.transport.abort()
        r = await asyncio.wait_for(cell, 20)
        assert r.lost or r.ok, r
        k.comm_send(cid, {'after': 1})
        await until(of(seen, 'comm_msg', lambda m: m['content']['data'].get('echo') == {'after': 1}))
        assert (await k.execute('y')).text == '2'
    finally: await k.shutdown()

async def test_a_lost_execute_reply_is_recovered_by_the_probe(tmp_path, monkeypatch):
    "When the reply and idle never arrive, a shell `kernel_info` answered while the run waits settles it as lost."
    monkeypatch.setattr(kmod, 'QUIET', .5)
    k = await started('gateway', tmp_path)
    try:
        route = k.kc.on_jmsg
        def lossy(msg):
            idle = msg.get('content', {}).get('execution_state') == 'idle'
            if msg.get('msg_type') == 'execute_reply' or (idle and msg['parent_header'].get('msg_type') == 'execute_request'): return
            return route(msg)
        k.kc.on_jmsg = lossy
        r = await asyncio.wait_for(k.execute('print("ran")'), 15)
        assert r.lost and 'ran' in r.text
        k.kc.on_jmsg = route
        assert (await k.execute('1')).ok
    finally: await k.shutdown()

async def test_the_probe_does_not_settle_a_long_silent_cell(tmp_path, monkeypatch):
    monkeypatch.setattr(kmod, 'QUIET', .3)
    k = await started('gateway', tmp_path)
    try:
        t = time.monotonic()
        r = await k.execute('import time; time.sleep(2); 5')
        assert r.ok and not r.lost and r.text == '5' and time.monotonic() - t >= 2
    finally: await k.shutdown()

@both
async def test_a_timeout_bounds_the_whole_run(tmp_path, transport):
    "Output that keeps coming does not extend the deadline, and what the abandoned cell prints later is not callback output."
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        t = time.monotonic()
        r = await k.execute('import time\nfor i in range(15): print(i, flush=True); time.sleep(.1)\nprint("late")', timeout=.6)
        assert not r.ok and 'timed out' in r.error and '0' in r.text and time.monotonic() - t < 1.5
        await asyncio.sleep(1.5)
        assert not any('late' in m['content'].get('text', '') for m in seen)
    finally: await k.shutdown()

async def test_an_on_output_error_is_the_callers_to_see(tmp_path):
    k = await started('direct', tmp_path)
    try:
        with pytest.raises(ZeroDivisionError): await k.execute('print(1)', on_output=lambda o: 1/0)
        await asyncio.sleep(.5)    # an execute sent while the abandoned one is still finishing can stall ipykernel 7.3 (see the report)
        assert (await k.execute('2')).ok
    finally: await k.shutdown()

@both
async def test_restart_and_shutdown_tell_subscribers(tmp_path, transport):
    k, seen = await started(transport, tmp_path), []
    try:
        k.subscribe(seen.append)
        await k.restart()
        await until(lambda: {'type': 'kernel_restart'} in seen)
        assert (await k.execute('1')).ok, 'and the router reads the new kernel'
    finally: await k.shutdown()
    assert seen[-1] == {'type': 'kernel_gone'}

async def test_a_kernel_restarted_after_an_ignored_interrupt_says_so(tmp_path):
    k, seen = await started('direct', tmp_path), []
    try:
        k.subscribe(seen.append)
        stubborn = asyncio.create_task(k.execute('import time\nwhile True:\n    try: time.sleep(10)\n    except KeyboardInterrupt: pass'))
        await asyncio.sleep(.5)
        assert (await k.stop(timeout=.5))['forced']
        await until(lambda: {'type': 'kernel_restart'} in seen)
        await asyncio.gather(stubborn, return_exceptions=True)
    finally: await k.shutdown()

async def test_comm_traffic_keeps_a_kernel_from_the_idle_reaper(tmp_path):
    "Widgets updated from a kernel thread count as use, and the reaper's close is a `kernel_gone`."
    pool, seen = KernelPool(idle=1), []
    try:
        k = await pool.get('nb', cwd=str(tmp_path), inspect=False)
        k.subscribe(seen.append)
        await k.execute("import threading, time\nfrom ipykernel.comm import Comm\nc = Comm(target_name='kunda.tick')\n"
                        "def tick():\n    for i in range(12): time.sleep(.25); c.send({'i': i})\nthreading.Thread(target=tick).start()")
        for _ in range(4):
            await asyncio.sleep(.6)
            assert await pool.reap() == [] and k.alive, 'comm traffic in the last idle window'
        await until(of(seen, 'comm_msg', lambda m: m['content']['data'].get('i') == 11))
        await asyncio.sleep(1.5)
        await pool.reap()
        await until(lambda: 'nb' not in pool.kernels and seen[-1] == {'type': 'kernel_gone'})    # the pool's own sweep may be the one closing it
    finally: await pool.close_all()

def test_a_kernel_without_comms_says_so():
    "ipymini and other languages carry no comm manager kunda relays to."
    for k in (Kernel(kernel='ipymini', inspect=False), Kernel(lang='julia', inspect=False)):
        assert not k.comms
        with pytest.raises(kmod.CommsUnsupported): k.comm_send('c1', {})
    assert Kernel(inspect=False).comms and GatewayKernel(None, inspect=False).comms
