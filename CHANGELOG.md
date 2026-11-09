# Release notes

<!-- do not remove -->

## Unreleased

- New `kunda.trace`: `run_traced` runs a cell and returns its values line by line (one event for each line, call, return or exception), with limits on events, value size and time. A kernel that is not Python gives a plain error.

## 0.0.15

- `KernelPool`, `Kernel`, `GatewayKernel` and `bootstrap_src` default to port 0, so the OS gives each inspector a free port. Before, the default was 8000, and an inspector took a port that a person may want for their own server. The kernel still finds its inspector through the dhrishti registry.

## 0.0.14

- `make_venv(root)` makes a project's `.venv` with the host's Python minor version and kernel support, keeps an existing one, and refuses a `.venv` folder with no interpreter.
- `python_for` takes a venv from `roots` only when the caller sets `borrow=True`. Before, a folder with no venv of its own used the first venv among the open folders.

## 0.0.13

Needs dhrishti 0.1.12.

- A kernel in a chosen venv imports only that venv's packages. Before, kunda added every folder of the host's `sys.path` to the kernel when the two Python versions matched, so a notebook could import packages its venv did not have. The inspector still loads from the host, through a private finder that serves only dhrishti and its own dependencies, and only to dhrishti.
- A kernel on the host's own Python works as before.

## 0.0.12
- A gateway run whose kernel shell stopped reading now ends. When two probes in a row get no shell answer, the run is not a running cell, and the control channel still answers, the run ends with `lost=True`, `reason='shell_stopped'` and an error that says to restart the kernel. Each later `execute` returns the same outcome at once, until `restart`. Before, kunda asked again every 30 s and the cell never ended. A socket that dropped keeps the old recovery.
- `ExecOutcome` has a new field, `reason`.
- `ipykernel_version` reads an interpreter's ipykernel version from its metadata, without importing ipykernel. `ipykernel_notice` gives a message for ipykernel 7.0 to 7.3, which can stop answering. `kernel_support` puts it in the ipykernel entry as `notice`, and a started `Kernel` or `GatewayKernel` keeps it in `notice`.
- `install_kernel_support` installs `ipykernel>=7.4` (`kernel_requirements`), not the host's exact version, and refuses a Python older than 3.11 before it installs anything.

## 0.0.11
- kunda needs ipykernel 7.4 or later. ipykernel 7.0 to 7.3 can stop reading its shell socket when a request comes at the same moment as a reply goes out (ipykernel PR #1529). Kunda's check for a lost reply sends `kernel_info` about 2 s into a cell, so a cell of about 2 s could hang until the kernel restarted.

## 0.0.10
- `execute` now sends `on_output` the event `{'output_type': 'clear_output'}` when the outputs clear. With `wait=True` the event comes immediately before the next output's event. A consumer that builds the output list resets it on this event. Every other event and the final outputs are the same as before.

## 0.0.9
- A gateway kernel starts again with jupyasyncclient 0.2.21. That client no longer sends `argv` when it creates a kernel, so `GatewayKernel.start` now creates the kernel itself through the gateway API with `argv`, and then connects the client to that kernel.
- When the gateway websocket drops during a quiet run, the probe asks again after the client reconnects. Before, jupyasyncclient 0.2.21 failed the probe at once, and the run ended with a connection error in place of `lost`.
- kunda needs jupygate 0.0.5, jupyasyncclient 0.2.21 and jupywire 0.1.14 or later. These three releases work together.

## 0.0.8
- A gateway kernel can debug a cell. `GatewayKernel` now has `debug_start`, `debug_variables`, `debug_state`, `debug_evaluate`, `debug_complete`, `debug_control` and `debug_stop`, the same as the direct `Kernel`. Both share this code in `DebugClient`. The gateway sends each debugger request on the control channel and waits for its reply.
- A restart or a shutdown of a gateway kernel ends a debugger request that is still waiting, with an error, so the caller does not wait forever.

## 0.0.7
- `InspectorClient.bootstrap` runs its cell with a `BOOT_WAIT` (30 s) timeout; on a timeout it interrupts the kernel and tries once more on the next free port. Before, two kernels starting at once could pick the same inspector port, the loser's bootstrap never finished, and `Kernel.start` and `KernelPool.get` waited forever.

## 0.0.6


## 0.0.5
Interpreter probes (`support._run` and `missing_kernel_module`) give the probed Python `/dev/null` as stdin, so a probe never reads or reconfigures the host's terminal

## 0.0.4
Public names for what hosts already reached for: `runtime_python`, `frozen_pythonpath`, `kernel_spec`, `venv_roots`, `InspectorClient` and `give_up_after`; the underscored names stay as aliases

## 0.0.3
pool and broker serve callers on several event loops: a stopped loop's start or sweep no longer holds a slot; dev deps are a `[dev]` extra

## 0.0.2
kunda means the vessel that holds the fire
