"Traced runs: the tracer on its own, and `run_traced` through a real ipykernel."
import asyncio, sys
import pytest
from kunda.kernel import Kernel
from kunda.trace import trace_cell

WAIT = 90

BSEARCH = """def bsearch(a, x):
    low, high = 0, len(a) - 1
    while low <= high:
        mid = (low + high) // 2
        if a[mid] < x: low = mid + 1
        elif a[mid] > x: high = mid - 1
        else: return mid
    return -1
bsearch([1, 3, 5, 7, 9, 11], 7)"""

def lines(out, n, event='line'): return [e for e in out['events'] if e['line'] == n and e['event'] == event]

def test_the_values_of_each_pass_show_per_line():
    out, res, err, _ = trace_cell(BSEARCH, {})
    assert res == 3 and err is None
    assert [e['locals_changed'] for e in lines(out, 4)] == [{'mid': '2'}, {'mid': '4'}, {'mid': '3'}]
    assert [e['step'] for e in out['events']] == sorted(e['step'] for e in out['events'])
    assert lines(out, 2)[0]['locals_changed'] == {'low': '0', 'high': '5'}

def test_a_long_loop_is_sampled_with_a_counter():
    out, res, err, _ = trace_cell("t = 0\nfor i in range(10000):\n    t += i\nt", {})
    assert res == 49995000
    body = lines(out, 3)
    assert len(body) == 100
    assert [e for e in out['events'] if e['event'] == 'skip' and e['line'] == 3][0]['count'] == 9900
    assert body[-1]['locals_changed'] == {'t': '49995000'}
    assert len(out['events']) < 500

def test_recursion_shows_depth_and_return_values():
    out, res, err, _ = trace_cell("def fact(n):\n    if n <= 1: return 1\n    return n * fact(n - 1)\nfact(4)", {})
    assert res == 24
    assert max(e['depth'] for e in out['events']) == 5   # module + 4 calls
    assert [e['locals_changed']['<return>'] for e in out['events'] if e['event'] == 'return' and e['line'] == 2][:1] == ['1']
    assert [e['locals_changed'] for e in out['events'] if e['event'] == 'call'][-4:] == [{'n': '4'}, {'n': '3'}, {'n': '2'}, {'n': '1'}]

def test_an_error_keeps_the_events_before_it():
    out, res, err, tb = trace_cell("x = 1\ny = x / 0\nz = 3", {})
    assert isinstance(err, ZeroDivisionError) and out['error'].startswith('ZeroDivisionError')
    assert lines(out, 1)[0]['locals_changed'] == {'x': '1'}
    assert not lines(out, 3)
    assert 'exception' in [e['event'] for e in out['events']]

def test_a_huge_object_is_clipped_not_serialised():
    out, *_ = trace_cell("big = list(range(1_000_000))\ns = 'x' * 10_000_000\nclass A:\n    def __repr__(self): return 'y' * 5000\na = A()\nd = [A() for _ in range(3)]\nz = 0", {}, max_repr=60)
    seen = {}
    for e in out['events']: seen.update(e['locals_changed'])
    assert all(len(v) <= 60 for v in seen.values()), seen
    assert seen['big'].startswith('[0, 1, 2') and '\u2026' in seen['big']
    assert out['secs'] < 2

def test_tracing_stops_at_the_time_cap_and_the_cell_finishes():
    out, res, err, _ = trace_cell("n = 0\nfor i in range(3_000_000): n += 1\nn", {}, secs=.05, keep=5)
    assert res == 3_000_000 and out['truncated'] and 'seconds' in out['reason']

def test_the_event_cap_holds():
    out, *_ = trace_cell("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\nf = 6", {}, max_events=4)
    assert len(out['events']) == 4 and out['truncated']

def test_threads_started_by_the_cell_do_not_crash_it():
    out, res, err, _ = trace_cell("import threading\nr = []\nt = threading.Thread(target=lambda: r.append(1))\nt.start(); t.join()\nr", {})
    assert res == [1] and err is None

def test_the_hook_is_gone_afterwards():
    before = sys.gettrace()
    trace_cell("x = 1", {})
    trace_cell("1/0", {})
    assert sys.gettrace() is before

def test_a_watch_list_keeps_only_those_names():
    out, *_ = trace_cell("a = 1\nb = 2\nc = a + b", {}, watch=['c'])
    seen = {k for e in out['events'] for k in e['locals_changed']}
    assert seen == {'c'}

# a real kernel

async def started(tmp_path):
    return await asyncio.wait_for(Kernel(cwd=str(tmp_path), inspect=False).start(), WAIT)

async def test_run_traced_in_a_kernel_returns_events_and_the_normal_output(tmp_path):
    k = await started(tmp_path)
    try:
        r = await asyncio.wait_for(k.run_traced("print('hi')\n" + BSEARCH), WAIT)
        assert r.ok and 'hi' in r.outputs[0]['text']
        assert any(o['output_type'] == 'execute_result' and '3' in o['data']['text/plain'] for o in r.outputs)
        assert not any(o.get('data', {}).get('application/vnd.kunda.trace+json') for o in r.outputs)
        mids = [e['locals_changed'] for e in r.events if e['line'] == 5 and e['event'] == 'line']
        assert mids == [{'mid': '2'}, {'mid': '4'}, {'mid': '3'}]
        assert (await asyncio.wait_for(k.execute("'mid' in globals(), 'trace_cell' in globals(), 'bsearch' in globals()"), WAIT)).text == '(False, False, True)'
    finally: await k.shutdown()

async def test_run_traced_error_still_returns_the_events_before_it(tmp_path):
    k = await started(tmp_path)
    try:
        r = await asyncio.wait_for(k.run_traced("x = 4\ny = x / 0\nz = 1"), WAIT)
        assert not r.ok and 'ZeroDivisionError' in r.error
        assert any(e['locals_changed'] == {'x': '4'} for e in r.events)
        assert 'kunda-trace' in ''.join(o.get('traceback', [''])[0] for o in r.outputs if o['output_type'] == 'error') or r.outputs
    finally: await k.shutdown()

async def test_run_traced_sees_names_from_earlier_cells_and_threads_do_not_break_it(tmp_path):
    k = await started(tmp_path)
    try:
        assert (await asyncio.wait_for(k.execute("seed = 41"), WAIT)).ok
        r = await asyncio.wait_for(k.run_traced("import threading\nout = []\nt = threading.Thread(target=lambda: out.append(seed + 1))\nt.start(); t.join()\nout"), WAIT)
        assert r.ok and '[42]' in r.outputs[-1]['data']['text/plain']
    finally: await k.shutdown()

async def test_run_traced_with_a_timeout_returns_instead_of_hanging(tmp_path):
    k = await started(tmp_path)
    try:
        r = await asyncio.wait_for(k.run_traced("import time\nx = 1\ntime.sleep(30)", timeout=2), WAIT)
        assert not r.ok and 'timed out' in r.error
    finally: await k.shutdown()
