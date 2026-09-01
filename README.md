# kunda

A *kuṇḍa* is the vessel a fire is kept in, not the fire itself. `ipymini` and `kernmini` are the
fire; this is what holds several of them alive, decides which interpreter each burns in, and puts
one out when there are too many.

kunda is a library, not a CLI. It answers with plain dicts and dataclasses, so an editor, a
notebook server and a test all read the same thing.

## Install

```sh
pip install kunda                # which interpreter a folder uses, and a kernel client
pip install "kunda[kernels]"     # + ipykernel and ipymini to start
pip install "kunda[inspect]"     # + live variables inside a running kernel
pip install "kunda[gateway]"     # + kernels reached over a websocket instead of started here
```

`kunda.pythons` imports nothing but fastcore, so asking which interpreter a folder uses costs you
no Jupyter dependency at all.

## Which interpreter does this folder use?

```python
from kunda import python_for, find_pythons, venv_env

python_for('~/code/myrepo/src', stop='~/code/myrepo')   # the venv nearest that file
find_pythons(roots=['~/code'], current=...)             # every interpreter worth offering
venv_env(python)                                        # a child environment for it
```

`python_for` walks up from a path and stops where you say — `stop` is the open folder, so a venv
belonging to something *above* your workspace is never borrowed. It falls through in a fixed order:
the walk up, then the default you nominate, then the first venv among your roots, then `None`,
which means "this interpreter" to everything downstream.

`venv_env` also strips a frozen host's `PYTHONHOME` and `PYTHONPATH`. A child that keeps them
imports the bundle's standard library under another interpreter and dies somewhere that names
nothing to do with the cause.

## Running one kernel

```python
from kunda import Kernel

k = Kernel(cwd='~/code/myrepo', python=..., kernel='ipymini')
await k.start()
out = await k.execute('df.head()', on_output=print)   # streams while it runs
out.ok, out.text, out.execution_count
await k.complete('df.he', 5)
await k.restart()      # same kernel, empty namespace
await k.shutdown()
```

A cell that raises comes back as a result, not an exception: `out.ok` is False and `out.text` holds
the traceback the way a terminal would show it. The kernel stays usable.

Before the protocol can confuse matters, `missing_kernel_module` asks the environment directly
which module it is short of — otherwise an environment without `ipykernel` reports only that the
kernel died before answering `kernel_info`, which says nothing about the remedy.

## Keeping several alive

```python
from kunda import KernelPool, RuntimeBroker

pool = KernelPool(broker=RuntimeBroker(max_kernels=12), idle=30*60)
k = await pool.get('notebook-1', cwd=..., python=..., inspect=True)
pool.peek('notebook-1')      # the live one, never something still starting
await pool.close('notebook-1')
await pool.close_all()
```

One key, one kernel, however many callers ask at once — two panels opening the same notebook get
the same namespace rather than one orphaned kernel each. A kernel that fails to start is not left
in the pool. Nothing idle is reaped while a cell is running, and `idle=0` switches reaping off.

At the ceiling, `RuntimeBroker` names the kernel it would close rather than failing: the
alternative is a notebook that will not open with no way to learn why. `KUNDA_MAX_KERNELS` and
`KUNDA_KERNEL_IDLE` set the defaults.

A language with no Jupyter kernel reaches whatever runner you supply:

```python
KernelPool(runner_for=lambda lang: MyRustRunner if lang == 'rust' else None,
           known_kernels={'julia': 'julia-1.10'})
```

## What a kernel needs before it can start

```python
from kunda import kernel_support, install_kernel_support, installable

kernel_support(python)          # can it import ipykernel? ipymini? with what error?
installable(python)             # never this interpreter, never inside a signed bundle
install_kernel_support(python)  # uv where there is one, else pip, else ensurepip first
```

What gets installed is pinned to the versions *you* are running, because that combination is the
one known to work. Asking an index for the newest of each is what produces `ipymini 0.1.20` beside
`kernmini 0.1.9`, which import each other and do not fit.

An installer that returns 0 and leaves a kernel that will not import is reported as a failure of
the packages, not of the installer.

## Live variables

With `kunda[inspect]`, a kernel started with `inspect=True` runs a bootstrap that starts a
[dhrishti](https://pypi.org/project/dhrishti/) inspector inside it, and `kunda.registry` finds the
live ones. The bootstrap pins the inspector to *your* dhrishti while every other import stays
project-local, and only where the kernel's Python is the same minor version as yours — a frozen
build ships bytecode another version reads the magic number of and refuses.

## Status

The kernel client is `jupyter_client` as it stands. Swapping it for
[conkernelclient](https://pypi.org/project/conkernelclient/) and
[jupywire](https://pypi.org/project/jupywire/) is the next change, and it happens behind the tests
in this repo rather than as part of moving the code here.
