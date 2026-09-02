__version__ = "0.0.2"

# The names a host reaches for. `kunda.pythons` imports nothing but fastcore, so asking which
# interpreter a folder uses costs nothing; everything below it wants jupyter_client.
from .pythons import find_pythons, nearest_python, project_python, python_for, use_app, venv_env
from .support import install_kernel_support, kernel_support, installable
from .spec import ExecOutcome, KernelStartError, output_text
from .kernel import Kernel, ipymini_available
from .pool import KernelLimit, KernelPool, RuntimeBroker

__all__ = ['find_pythons', 'nearest_python', 'project_python', 'python_for', 'use_app', 'venv_env',
           'install_kernel_support', 'kernel_support', 'installable', 'ExecOutcome',
           'KernelStartError', 'output_text', 'Kernel', 'ipymini_available',
           'KernelLimit', 'KernelPool', 'RuntimeBroker']
