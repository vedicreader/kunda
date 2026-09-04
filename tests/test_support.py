"What a kernel needs before it can start, and whether this environment may be written to."
import sys
from pathlib import Path
import pytest
from kunda.support import (HOST_PY, KERNEL_PACKAGES, as_installed, import_failure, inspector_support,
                           installable, kernel_support, support_paths, work_dir)

def test_this_interpreter_is_never_installed_into():
    "Installing into the environment doing the installing is how a host breaks itself mid-run."
    assert installable(sys.executable) is False
    assert installable('') is False and installable(None) is False
    assert installable('/tmp/other/.venv/bin/python') is True

def test_a_signed_bundles_own_interpreter_is_refused():
    "Writing inside a code-signed app breaks its signature, and the failure comes much later."
    assert installable('/Applications/X.app/Contents/Resources/python') is False
    assert installable('/Applications/X.app/Contents/MacOS/python') is False

def test_what_gets_installed_is_pinned_to_what_is_running_here():
    """Asking an index for the newest of each is what produced `ipymini 0.1.20` beside
    `kernmini 0.1.9`, which import each other and do not fit."""
    out = as_installed(['pytest'])
    assert out[0].startswith('pytest=='), 'a package the host has is pinned to the host is version'
    assert as_installed(['not_a_real_package_xyz']) == ['not_a_real_package_xyz'], 'and one it has is left loose'
    assert len(as_installed()) == len(KERNEL_PACKAGES)

def test_probing_this_interpreter_finds_the_kernel_it_is_running_with():
    got = kernel_support(sys.executable)
    assert set(got) == {'ipykernel', 'ipymini'}
    assert got['ipykernel']['available'] and got['ipykernel']['version']
    assert got['ipykernel']['error'] == ''

def test_probing_an_interpreter_that_is_not_one_reports_rather_than_raises():
    got = kernel_support('/definitely/not/a/python')
    assert all(not v['available'] for v in got.values())
    assert all(isinstance(v['error'], str) for v in got.values())

def test_the_inspector_answer_is_cached_but_can_be_refreshed():
    "A person who installs something by hand should not have to restart the host to be believed."
    first = inspector_support(sys.executable)
    assert set(first) >= {'available', 'version', 'error'}
    assert inspector_support(sys.executable) == first, 'the second ask is the cached one'
    assert set(inspector_support(sys.executable, refresh=True)) == set(first)

def test_inspector_import_errors_are_recognized_anywhere_in_the_message():
    assert not import_failure('ValueError: bad shape')
    assert import_failure('numpy ABI advice\nImportError: numpy.core.multiarray failed to import')

def test_a_child_is_given_a_directory_it_can_actually_write_in(tmp_path):
    """A double-clicked app inherits `/`, and one started from `open` inherits the bundle, which is
    read-only. A kernel launched there cannot write a file beside itself and says nothing useful."""
    assert work_dir(tmp_path) == str(tmp_path)
    assert Path(work_dir()).is_dir()

def test_the_paths_a_kernel_may_borrow_are_all_real_and_absolute():
    "A relative or missing entry handed to a kernel is a silent import failure inside it."
    for p in support_paths(): assert Path(p).is_absolute() and Path(p).exists()

def test_the_host_version_is_what_a_borrowed_path_is_gated_on():
    "A frozen build ships bytecode for one version; another reads the magic number and refuses."
    assert HOST_PY == tuple(sys.version_info[:2])
