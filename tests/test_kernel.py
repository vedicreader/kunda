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
