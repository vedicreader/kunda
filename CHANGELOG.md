# Release notes

<!-- do not remove -->

## 0.0.6
kunda is the only reader of each kernel's iopub and shell replies, on both transports, and routes every message by its parent through `MessageRouter`. `GatewayKernel` no longer uses jupyasyncclient's `Run`, which kept only its own run's output and dropped comm buffers.

- `k.subscribe(fn)` delivers comm_open, comm_msg and comm_close whole (header, parent, metadata, content, buffers), output whose parent is not a running execute (a comm handler's print), and `kernel_restart` and `kernel_gone` events, through a bounded `Feed` that never blocks.
- `k.comm_send(...)` and `await k.comm_info(...)` work during a running cell; kernels without comms raise `CommsUnsupported`.
- Output-widget capture: while an `OutputModel` captures an execute, its output goes to subscribers tagged `output_comm_id`, not into the cell, so `with out: clear_output()` no longer wipes the cell's widget view.
- `complete`, `inspect_obj`, `comm_info` and `execute` can overlap without dropping each other's replies.
- A gateway run whose execute_reply was lost across a reconnect settles with `ExecOutcome.lost`, found by a `kernel_info` probe after `QUIET` seconds of silence.
- `clear_output` is honoured on the gateway too, and `timeout` bounds the whole run on both transports.
- Comm traffic counts as activity, so the pool's idle reaper spares a kernel in use through widgets.
- Needs jupyasyncclient 0.2.12.

## 0.0.5
Interpreter probes (`support._run` and `missing_kernel_module`) give the probed Python `/dev/null` as stdin, so a probe never reads or reconfigures the host's terminal

## 0.0.4
Public names for what hosts already reached for: `runtime_python`, `frozen_pythonpath`, `kernel_spec`, `venv_roots`, `InspectorClient` and `give_up_after`; the underscored names stay as aliases

## 0.0.3
pool and broker serve callers on several event loops: a stopped loop's start or sweep no longer holds a slot; dev deps are a `[dev]` extra

## 0.0.2
kunda means the vessel that holds the fire
