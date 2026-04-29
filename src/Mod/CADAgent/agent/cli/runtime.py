# SPDX-License-Identifier: LGPL-2.1-or-later
"""Back-compat shim. The shared agent runtime moved to
:mod:`agent.runtime` (Step 10 of the harness refactor):

* ``build_options`` → ``agent.runtime.options.build_options``
* ``_post_bash_probe`` → ``agent.runtime.auto_probe.post_bash_probe``
* ``_stop_gate`` → ``agent.runtime.stop_gate.stop_gate``

Existing call sites (currently ``cli/dock_runtime`` only) still import
``cli_runtime.build_options``; that path keeps working until Step 18
deletes ``agent/cli/`` entirely.
"""

from __future__ import annotations

from ..runtime.auto_probe import (  # noqa: F401
    extract_script_verdict as _extract_script_verdict,
    post_bash_probe as _post_bash_probe,
)
from ..runtime.options import build_options  # noqa: F401
from ..runtime.stop_gate import GATE_ATTEMPTS_CAP as _GATE_ATTEMPTS_CAP  # noqa: F401
from ..runtime.stop_gate import stop_gate as _stop_gate  # noqa: F401
