# Release notes

<!-- do not remove -->

## 0.0.5
Interpreter probes (`support._run` and `missing_kernel_module`) give the probed Python `/dev/null` as stdin, so a probe never reads or reconfigures the host's terminal

## 0.0.4
Public names for what hosts already reached for: `runtime_python`, `frozen_pythonpath`, `kernel_spec`, `venv_roots`, `InspectorClient` and `give_up_after`; the underscored names stay as aliases

## 0.0.3
pool and broker serve callers on several event loops: a stopped loop's start or sweep no longer holds a slot; dev deps are a `[dev]` extra

## 0.0.2
kunda means the vessel that holds the fire
