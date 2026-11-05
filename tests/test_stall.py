"A shell that stops reading (ipykernel 7.0 to 7.3, ipykernel#1529) ends its run and says so, while a busy cell and a dropped socket keep the old paths. No real kernel and no real waits."
import asyncio
from kunda import kernel as kmod
from kunda.kernel import GatewayKernel, Kernel, _Run

class FakeClient:
    "A gateway client whose shell and control channels answer `kernel_info` or time out at once."
    def __init__(self, shell=False, control=True):
        self.shell, self.control, self._ws, self.channels_running, self.sent = shell, control, object(), True, []
    async def kernel_info(self, timeout=None):
        if not self.shell: raise asyncio.TimeoutError
    async def kernel_info_request(self, channel='shell', timeout=None):
        if not (self.control if channel == 'control' else self.shell): raise asyncio.TimeoutError
    def execute(self, code, **kw): self.sent.append(code); return 'm1'
    async def restart_kernel(self): pass
    async def wait_for_ready(self, timeout=None): pass

def gateway_kernel(**kw):
    k = GatewayKernel(None, inspect=False)
    k.kc, k._alive = FakeClient(**kw), True
    return k

def sent_run(k, **kw):
    "A run as `execute` leaves it after sending: on the socket it went out on."
    run = _Run()
    run.via = k._link()
    for a, v in kw.items(): setattr(run, a, v)
    return run

async def probes(k, run, n):
    for _ in range(n): await k._probe(run)

async def test_a_shell_that_stopped_reading_ends_the_run_and_every_execute_after_it_until_restart():
    k = gateway_kernel()
    run = sent_run(k)
    await probes(k, run, 1)
    assert not run.done.is_set(), 'one unanswered probe is not enough: a comm handler may hold the shell'
    await probes(k, run, 1)
    o = run.outcome()
    assert run.done.is_set() and o.lost and o.reason == 'shell_stopped' and not o.ok and 'restart' in o.error, o
    assert k.stalled == 'shell_stopped'
    r = await k.execute('1')
    assert (r.reason, r.lost, r.ok) == ('shell_stopped', True, False) and k.kc.sent == [], 'answered at once, and nothing sent'
    await k.restart()
    assert k.stalled is None

async def test_a_finished_run_whose_reply_never_came_is_a_stopped_shell_on_any_socket():
    k = gateway_kernel()
    run = sent_run(k, idle=True, busy=True, via=object())
    await probes(k, run, 2)
    assert run.outcome().reason == 'shell_stopped'

async def test_a_busy_cell_keeps_waiting_however_long_it_is_silent():
    k = gateway_kernel()
    run = sent_run(k, busy=True)
    await probes(k, run, 5)
    assert not run.done.is_set() and run.deaf == 0 and k.stalled is None

async def test_a_silent_control_channel_keeps_the_old_retry():
    "A kernel that answers on no channel is gone or unreachable, not stalled; the connection paths deal with that."
    k = gateway_kernel(control=False)
    run = sent_run(k)
    await probes(k, run, 4)
    assert not run.done.is_set() and k.stalled is None

async def test_a_run_sent_on_a_socket_that_has_since_dropped_is_not_called_stalled():
    "Its busy status may have gone with the old socket."
    k = gateway_kernel()
    run = sent_run(k, via=object())
    await probes(k, run, 4)
    assert not run.done.is_set()

async def test_a_shell_that_answers_still_means_a_lost_reply(monkeypatch):
    monkeypatch.setattr(kmod, 'QUIET', 0)
    k = gateway_kernel(shell=True)
    run = sent_run(k)
    await probes(k, run, 1)
    o = run.outcome()
    assert o.lost and o.reason is None and o.ok

def test_a_busy_status_marks_its_run():
    k = gateway_kernel()
    k._runs['m1'] = run = _Run()
    k._dispatch({'msg_type': 'status', 'content': {'execution_state': 'busy'}, 'parent_header': {'msg_id': 'm1'}})
    assert run.busy and not run.idle

async def test_a_kernel_on_a_stalling_ipykernel_carries_a_notice(tmp_path):
    (tmp_path/'pyvenv.cfg').write_text('home = /nowhere\n')
    (tmp_path/'lib/python3.12/site-packages/ipykernel-7.3.0.dist-info').mkdir(parents=True)
    k = Kernel(python=str(tmp_path/'bin/python'), inspect=False)
    await k._check_ipykernel()
    assert k.notice['version'] == '7.3.0' and 'Upgrade it to 7.4' in k.notice['message']
    k = Kernel(inspect=False)
    await k._check_ipykernel()
    assert k.notice is None
