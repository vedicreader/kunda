# Decisions

This page lists the decisions that a maintainer must know. Each entry gives the decision, the reason, the version, and the place in the code.
This repo has no CLAUDE.md. The house style and the rules of the package family are in Leela's CLAUDE.md. The changes of each release are in the [CHANGELOG](../CHANGELOG.md).

## What lives here, what does not

- **kunda is the layer above the kernel.** It picks the interpreter of a folder, says what that interpreter is missing, starts and runs kernels, and keeps a pool of them. The kernel is `ipymini` or `ipykernel`, the protocol is `jupywire`, and the in-kernel inspector is `dhrishti`. kunda does not copy them. (1 Sep 2026) `nbs/00_pythons.ipynb` to `nbs/05_pool.ipynb`.
- **kunda knows Jupyter kernels only.** A host gives its other runners with `runner_for` and its languages with `known_kernels` and the kernelspec map. kunda does not import a language registry. (1 Sep 2026) `KernelPool`, `kernelspec_for`, `kernel_spec`.
- **`python_for` takes plain arguments, not a session.** The host passes `stop`, `roots` and `default`. (1 Sep 2026) `python_for` in `nbs/00_pythons.ipynb`.
- **`kunda.pythons` imports only fastcore.** To ask which interpreter a folder uses must not need Jupyter. `nbs/00_pythons.ipynb`.
- **The kernels, the inspector and the gateway are plain dependencies, not extras.** Leela uses all three, so a split gave nothing. (4 Sep 2026) `pyproject.toml`.
- **Names that hosts use are public.** `runtime_python`, `frozen_pythonpath`, `kernel_spec`, `venv_roots`, `InspectorClient` and `give_up_after`. The names with `_` stay as aliases. (0.0.4)

## Interpreters and kernel support

- **A probe reports. It does not raise.** A missing interpreter is an answer of `kernel_support`. (1 Sep 2026) `kernel_support` in `nbs/01_support.ipynb`.
- **A probe does not install.** Only `install_kernel_support` installs, with uv first and then pip. It pins the versions that the host runs, and checks the import after. (1 Sep 2026) `as_installed`, `install_kernel_support`.
- **Never install into this interpreter or into a signed bundle.** A path under `/Contents/Resources/` or `/Contents/MacOS/` is refused. `installable`.
- **A frozen app runs its helpers with the bundled Python.** `runtime_python` gives py2app's helper, and `frozen_pythonpath` gives its module paths. A child gets the environment with the bundle variables removed. `runtime_python`, `frozen_pythonpath` in `nbs/03_spec.ipynb`, `BUNDLE_ONLY`, `clean_env`.
- **Probes get `/dev/null` as stdin.** A probe must not read or change the terminal of the host. (0.0.5) `_run` in `nbs/01_support.ipynb`.

## Kernels and the pool

- **An error in a cell is a result, not an exception.** `ExecOutcome` holds it, and the kernel stays up. A lost gateway reply is `ExecOutcome.lost`. (0.0.6) `ExecOutcome` in `nbs/03_spec.ipynb`.
- **One router reads every kernel message.** `MessageRouter` is the base of `Kernel` and `GatewayKernel`. It settles runs, matches replies, tracks Output widgets and sends comms and other output to subscribers through a bounded `Feed`. (0.0.6) `nbs/04_kernel.ipynb`.
- **Both kernels share one debugger.** `DebugClient` holds the debug calls. The gateway sends them on the control channel. A restart or shutdown ends a waiting request with an error. (0.0.8) `DebugClient`.
- **The inspector bootstrap has a timeout.** After `BOOT_WAIT` (30 s) it interrupts the kernel and tries one more time on the next free port, so two kernels that start together cannot both wait forever. (0.0.7) `BOOT_WAIT`, `InspectorClient.bootstrap`.
- **One kernel per key, and one limit for the process.** `RuntimeBroker` holds the limit across all pools. The pool and broker serve callers on many event loops, and a stopped loop does not hold a slot. (0.0.3) `nbs/05_pool.ipynb`.
- **The gateway packages move together.** kunda needs jupygate 0.0.5, jupyasyncclient 0.2.21 and jupywire 0.1.14 or later. `GatewayKernel.start` makes the kernel through the gateway API. (0.0.9) `GatewayKernel`.

## Release and docs

- **Dev dependencies are the `dev` extra, so CI can install them.** Give the imports of a test cell their own cell. (0.0.3, 19 Oct 2026) `pyproject.toml`.
