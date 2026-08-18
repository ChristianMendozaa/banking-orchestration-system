"""The one subprocess primitive both local-CLI backends (`cli_judge.py`, `cli_customer.py`)
build on: run a CLI (`claude` or `codex`), argv-only, with a hard timeout.

Split out of `cli_judge.py` once a second CLI-backed role (the simulated customer) needed
the exact same wrapper -- same failure modes (hung process, non-zero exit, a CLI that
reports its own errors on stdout instead of stderr), same reason to never use
`shell=True` (arguments here can carry arbitrary text -- a dossier, a scenario's system
prompt -- that must never be interpolated into a shell string).
"""

import asyncio


class CliError(RuntimeError):
    """Wraps a CLI failure (non-zero exit, timeout, or unparsable output) with enough of
    the process's own output to debug from the harness's structured logs alone."""


async def run_cli(*args: str, stdin: str | None, timeout_seconds: float, label: str) -> str:
    """One subprocess, argv-only, stdout captured and returned."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin.encode() if stdin is not None else None),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise CliError(f"{label} timed out after {timeout_seconds:.0f}s") from exc
    if process.returncode != 0:
        # Confirmed live (against codex): a CLI's `--json`-style mode can report its own
        # errors (e.g. a rejected response-format schema) as JSON events on *stdout*, not
        # stderr -- surfacing stderr alone silently dropped the one line that explained
        # the failure. Include both; whichever stream a given CLI actually uses, the real
        # message survives.
        raise CliError(
            f"{label} exited {process.returncode} "
            f"stderr={stderr.decode(errors='replace')[:500]!r} "
            f"stdout={stdout.decode(errors='replace')[:500]!r}"
        )
    return stdout.decode(errors="replace")
