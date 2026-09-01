"Which interpreter a folder runs in."
import os, sys
from pathlib import Path
import pytest
from kunda.pythons import (BUNDLE_ONLY, clean_env, find_pythons, nearest_marked, nearest_python,
                           project_python, python_for, strip_bundle, venv_env)

def mkvenv(root, name='.venv'):
    "A venv shaped the way `project_python` looks for one, without building a real one."
    d = root/name/'bin'; d.mkdir(parents=True)
    (d/'python').write_text(''); (d/'python').chmod(0o755)
    return d/'python'

def test_the_walk_up_stops_where_the_caller_says(tmp_path):
    """`stop` is the open folder. Without it a venv belonging to something above the workspace gets
    borrowed, and a kernel starts in an environment nobody in this project chose."""
    outer = tmp_path/'outer'; inner = outer/'repo'/'src'
    inner.mkdir(parents=True)
    py = mkvenv(outer)
    assert nearest_python(inner) == str(py), 'with no limit the walk finds it'
    assert nearest_python(inner, stop=outer/'repo') is None, 'stopped before it'

def test_the_nearest_venv_wins_over_a_further_one(tmp_path):
    "A checkout inside a monorepo has its own environment, and that is the one its code runs in."
    outer = tmp_path/'outer'; inner = outer/'repo'
    inner.mkdir(parents=True)
    mkvenv(outer); near = mkvenv(inner)
    assert nearest_python(inner) == str(near)

def test_python_for_falls_through_in_the_order_it_promises(tmp_path):
    "The walk up, then the caller's default, then the first venv among the roots, then nothing."
    proj = tmp_path/'proj'; proj.mkdir()
    assert python_for(proj) is None, 'nothing to find, so nothing claimed'
    assert python_for(proj, default='/usr/bin/python3') == '/usr/bin/python3'
    other = tmp_path/'other'; other.mkdir(); root_py = mkvenv(other)
    assert python_for(proj, roots=[other]) == str(root_py)
    own = mkvenv(proj)
    assert python_for(proj) == str(own), 'and its own beats both'

def test_project_python_prefers_the_conventional_name(tmp_path):
    "`.venv` before `venv`: a project with both made `.venv` on purpose and `venv` by accident."
    mkvenv(tmp_path, 'venv'); dot = mkvenv(tmp_path, '.venv')
    assert project_python([tmp_path]) == str(dot)

def test_nothing_anywhere_is_none_rather_than_a_guess(tmp_path):
    assert project_python([tmp_path]) is None and project_python([]) is None
    assert nearest_python(tmp_path/'does'/'not'/'exist') is None

def test_the_picker_lists_this_interpreter_the_current_one_and_the_venvs_in_reach(tmp_path):
    """A folder of checkouts holds a venv each, and the one already resolved may sit deeper than
    that scan goes — so it is listed explicitly or the picker cannot mark it."""
    repo = tmp_path/'repo'; repo.mkdir()
    inner = mkvenv(repo)
    rows = find_pythons([tmp_path], current=str(inner))
    paths = [r['path'] for r in rows]
    assert sys.executable in paths and str(inner) in paths
    assert len(paths) == len(set(paths)), 'no interpreter is offered twice'
    assert all(os.path.exists(p) for p in paths), 'and nothing offered is missing'
    assert rows[0]['path'] == sys.executable and rows[0]['label'] == 'this one'

def test_an_interpreter_that_is_not_there_is_not_offered(tmp_path):
    assert not any(r['path'].startswith(str(tmp_path)) for r in find_pythons([tmp_path]))

def test_naming_an_interpreter_puts_its_environment_in_front(tmp_path):
    py = mkvenv(tmp_path)
    env = venv_env(py, env={'PATH': '/usr/bin', 'UV_PROJECT_ENVIRONMENT': '/elsewhere',
                            'PYTHONHOME': '/wrong'})
    assert env['VIRTUAL_ENV'] == str(tmp_path/'.venv')
    assert env['PATH'].startswith(str(tmp_path/'.venv'/'bin') + os.pathsep)
    assert 'UV_PROJECT_ENVIRONMENT' not in env, 'it is read where the process ends up, not here'
    assert 'PYTHONHOME' not in env

def test_naming_none_claims_nothing_beyond_bundle_hygiene():
    assert venv_env(None, env={'PATH': '/bin'}) == {'PATH': '/bin'}

def test_a_frozen_hosts_redirection_is_dropped_and_only_then():
    "Outside a bundle this returns what it was given; inside, the bundle's own state goes."
    given = {'PYTHONHOME': '/somewhere', 'PATH': '/bin'}
    assert strip_bundle(dict(given), frozen=False) == given
    out = strip_bundle({n: 'x' for n in BUNDLE_ONLY} | {'PATH': '/bin'}, frozen=True)
    assert not (set(out) & set(BUNDLE_ONLY)) and out['PYTHONUTF8'] == '1' and out['PATH'] == '/bin'

def test_nearest_marked_answers_for_files_and_directories_alike(tmp_path):
    "`.venv/bin/python` asks about a file and `.git` about a directory; one walk answers both."
    repo = tmp_path/'repo'; (repo/'.git').mkdir(parents=True)
    deep = repo/'a'/'b'; deep.mkdir(parents=True)
    assert nearest_marked(deep, ('.git',))[0] == repo.resolve()
    assert nearest_marked(deep, ('nope',)) == (None, None)
    assert nearest_marked('/does/not/exist', ('.git',)) == (None, None)
