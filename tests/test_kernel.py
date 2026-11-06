"A kernel that really starts, runs code, and goes away again."
import asyncio, sys
import pytest
from kunda.kernel import Kernel, ipymini_available
from kunda.spec import ExecOutcome, KernelStartError, missing_kernel_module, output_text


async def run(k, code, **kw):
    return await k.execute(code, **kw)

async def test_a_kernel_starts_runs_and_shuts_down(tmp_path):
    "The whole life of one kernel, which is the thing every other feature is built on."
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        assert k.alive and k.pid
        out = await run(k, 'print("hello"); 6*7')
        assert out.ok and out.error is None
        assert 'hello' in out.text and '42' in out.text
        assert out.execution_count == 1
    finally:
        await k.shutdown()
    assert not k.alive

async def test_an_error_comes_back_as_an_error_not_as_a_raise(tmp_path):
    "A cell that raises is a result to display, not an exception in the host."
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        out = await run(k, 'raise ValueError("nope")')
        assert not out.ok and 'ValueError' in out.text and 'nope' in out.text
        assert out.error and 'ValueError' in out.error
        assert (await run(k, '1+1')).ok, 'and the kernel is still usable afterwards'
    finally: await k.shutdown()

async def test_the_namespace_survives_between_cells(tmp_path):
    "One kernel, one namespace: this is the whole reason a pool keeps them alive."
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        await run(k, 'kept = 11')
        assert '11' in (await run(k, 'kept')).text
    finally: await k.shutdown()

async def test_a_restart_clears_the_namespace_and_keeps_the_kernel(tmp_path):
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        await run(k, 'gone = 1')
        await k.restart()
        assert k.alive
        assert not (await run(k, 'gone')).ok, 'a restart is what forgetting looks like'
    finally: await k.shutdown()

async def test_output_arrives_while_it_runs_not_only_at_the_end(tmp_path):
    "A long cell that printed nothing until it finished would read as a hang."
    seen = []
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        await run(k, 'import sys\nfor i in range(3): print(i); sys.stdout.flush()',
                  on_output=lambda o: seen.append(o))
        assert seen, 'nothing streamed'
        assert '0' in output_text(seen)
    finally: await k.shutdown()

CLEARS = "print('a'); from IPython.display import clear_output; clear_output(); print('b')"

def in_order(events):
    "The events as `(output_type, text)`, with neighbouring stream fragments joined."
    res = []
    for e in events:
        if e['output_type'] == 'stream' and res and res[-1][0] == 'stream': res[-1] = ('stream', res[-1][1] + e['text'])
        else: res.append((e['output_type'], e.get('text')))
    return res

async def test_a_clear_output_streams_as_an_event_between_the_outputs(tmp_path):
    "A consumer that builds the list from the events keeps output the notebook cleared, unless it sees the clear."
    seen = []
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        out = await run(k, CLEARS, on_output=seen.append)
        assert in_order(seen) == [('stream', 'a\n'), ('clear_output', None), ('stream', 'b\n')], seen
        assert out.outputs == [{'output_type': 'stream', 'name': 'stdout', 'text': 'b\n'}]
    finally: await k.shutdown()

async def test_completion_answers_from_the_live_namespace(tmp_path):
    "Completion that cannot see what you just defined is completion from a parser, not a kernel."
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        await run(k, 'unmistakable_name = 1')
        got = await k.complete('unmistak', 8)
        assert any('unmistakable_name' in m for m in (got.get('matches') or []))
    finally: await k.shutdown()

async def test_the_kernel_runs_in_the_directory_it_was_given(tmp_path):
    "A relative path in a notebook means relative to the notebook, and this is what makes it so."
    (tmp_path/'marker.txt').write_text('found me')
    k = Kernel(cwd=str(tmp_path), inspect=False)
    await k.start()
    try:
        assert 'found me' in (await run(k, 'print(open("marker.txt").read())')).text
    finally: await k.shutdown()

async def test_a_bootstrap_that_never_ends_is_interrupted_and_tried_again(tmp_path, monkeypatch):
    """Two kernels starting together could pick the same inspector port. The loser's cell waited for a server that
    never started, so its `start` never returned and its shell took no other cell."""
    import kunda.kernel as K
    real, calls = K.bootstrap_src, []
    def wedged_once(*a, **kw):
        calls.append(a)
        return 'import time\nwhile True: time.sleep(.01)' if len(calls) == 1 else real(*a, **kw)
    monkeypatch.setattr(K, 'bootstrap_src', wedged_once)
    monkeypatch.setattr(K, 'BOOT_WAIT', 2.0, raising=False)
    k = Kernel(cwd=str(tmp_path))
    try:
        await asyncio.wait_for(k.start(), 60)
        assert len(calls) == 2 and k.base and k.boot_error is None, (calls, k.base, k.boot_error)
        assert (await run(k, '1+1', timeout=10)).ok, 'and the interrupted shell takes the next cell'
    finally: await k.shutdown()

def test_a_missing_kernel_module_is_named_before_the_protocol_can_confuse_it():
    """Without this, an environment lacking ipykernel reports only that the kernel died before
    answering `kernel_info`, which says nothing about the remedy."""
    assert missing_kernel_module(sys.executable, 'ipykernel') is None
    assert missing_kernel_module('/definitely/not/a/python', 'ipykernel') is None, 'cannot tell, so silent'

def test_an_unknown_kernel_name_falls_back_rather_than_failing(tmp_path):
    k = Kernel(cwd=str(tmp_path), kernel='not-a-kernel', inspect=False)
    assert k.kernel == 'ipykernel'

def test_a_non_python_language_turns_off_what_only_python_supports(tmp_path):
    "The inspector reads Python namespaces, so a Julia kernel is offered neither it nor ipymini."
    k = Kernel(cwd=str(tmp_path), lang='julia', inspect=True)
    assert k.inspect is False and k.kernel == 'ipykernel'

def test_outputs_flatten_the_way_a_terminal_would_show_them():
    assert output_text([{'output_type': 'stream', 'text': 'a'},
                        {'output_type': 'execute_result', 'data': {'text/plain': 'b'}}]) == 'ab'
    assert 'Boom' in output_text([{'output_type': 'error', 'ename': 'X', 'evalue': 'Boom'}])
    assert output_text([]) == ''

def test_an_outcome_says_what_it_holds_without_being_asked_twice():
    o = ExecOutcome(outputs=[{'output_type': 'stream', 'text': 'hi'}])
    assert o.ok and o.text == 'hi'

def test_no_ipykernel_with_the_shell_wedge_can_be_installed():
    "ipykernel 7.0 to 7.3 stops reading shell when a request lands as a reply leaves (ipykernel#1529), so a lost-reply probe never returns."
    import tomllib
    from importlib.metadata import version
    from pathlib import Path
    from packaging.requirements import Requirement
    from packaging.version import Version
    deps = tomllib.loads((Path(__file__).parents[1]/'pyproject.toml').read_text())['project']['dependencies']
    spec = next(r for r in map(Requirement, deps) if r.name == 'ipykernel').specifier
    assert not any(spec.contains(v) for v in ('7.0.0', '7.1.0', '7.2.0', '7.3.0')), spec
    assert not Version('7.0') <= Version(version('ipykernel')) < Version('7.4'), version('ipykernel')

async def test_a_chosen_venv_imports_only_its_own_packages_and_still_hosts_the_inspector(tmp_path):
    """The bootstrap once appended the host's whole `sys.path` to a kernel of the same Python. A venv that lacked
    a package then imported the host's copy, and nobody saw that the venv was incomplete."""
    import shutil, subprocess
    from kunda.support import install_kernel_support
    if not shutil.which('uv'): pytest.skip('needs uv to make a venv')
    venv = tmp_path/'venv'
    subprocess.run(['uv', 'venv', '-q', '--python', sys.executable, str(venv)], check=True)
    py = str(venv/'bin'/'python')
    try: install_kernel_support(py)
    except RuntimeError as e: pytest.skip(f'kernel support did not install: {e}')
    k = Kernel(cwd=str(tmp_path), python=py)
    try:
        await asyncio.wait_for(k.start(), 90)
        assert k.base and k.boot_error is None, k.boot_error
        assert (await run(k, 'kept = [1, 2]')).ok
        assert 'kept' in await k.names(), 'the inspector answers'
        for mod in ('jupygate', 'numpy'):   # the host has both; the venv has neither, and dhrishti did not load them
            out = await run(k, f'import {mod}')
            assert not out.ok and 'ModuleNotFoundError' in out.text, (mod, out.text)
        out = await run(k, 'import sys; print(any(".venv" in p and "kunda" in p for p in sys.path))')
        assert out.text.strip() == 'False', "the host's site-packages are not on the kernel's path"
    finally: await k.shutdown()
