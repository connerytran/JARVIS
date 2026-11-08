"""Ducking: lowers other apps' audio while JARVIS listens and speaks, using the Swift helper in bin/ducker.

Ducking is optional. If the helper is missing or fails, JARVIS logs one warning and works exactly as before.
Protocol (see docs/Ducking Plan.md): one command per line on the helper's stdin, one reply line on its stdout.
"""
import atexit
import logging
import os
import select
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DUCKER_PATH = Path(__file__).resolve().parent.parent / "bin" / "ducker"   # built from helpers/ducker
START_TIMEOUT = 5.0   # seconds to wait for "ready"; setup normally takes well under one
REPLY_TIMEOUT = 0.5   # seconds to wait for a reply; the helper answers in well under a millisecond
STOP_TIMEOUT = 2.0    # seconds to let the helper tear down at exit before killing it

_process: subprocess.Popen | None = None   # the running helper; None means ducking is off


def start() -> None:
    """Launches the helper and waits for "ready". On any failure, logs a warning and leaves ducking off."""
    global _process
    if not DUCKER_PATH.exists():
        logger.warning(f"Ducking off: no helper at {DUCKER_PATH} (build it: see docs/Ducking Plan.md).")
        return

    try:
        process = subprocess.Popen(
            [str(DUCKER_PATH), "--exclude-pid", str(os.getpid())],   # exclude us, so JARVIS's voice isn't ducked
            stdin=subprocess.PIPE,    # we write commands here
            stdout=subprocess.PIPE,   # and read replies here; stderr is inherited, so its logs print in our terminal
            text=True,                # str, not bytes
            bufsize=1,                # line-buffered: each line we write is sent as soon as it ends with "\n"
        )
    except OSError as e:
        logger.warning(f"Ducking off: couldn't launch the helper: {e}")
        return

    reply = _read_line(process, START_TIMEOUT)
    if reply != "ready":
        process.kill()   # if it's hung, stop it; if it already exited, this does nothing
        process.wait()
        logger.warning(f"Ducking off: helper didn't start (reply {reply!r}, exit code {process.returncode}).")
        return

    _process = process
    atexit.register(_stop)   # however JARVIS exits (normally, Ctrl-C, an exception), stop the helper first
    logger.info("Ducking on.")


def duck() -> None:
    """Lowers other apps' audio (fades over ~200 ms). Does nothing if ducking is off. Safe to repeat."""
    _send("duck")


def release() -> None:
    """Brings other apps' audio back (fades over ~800 ms). Does nothing if ducking is off. Safe to repeat."""
    _send("release")


def _send(command: str) -> None:
    """Sends one command and checks its reply. If the helper has died or stopped answering, turns ducking off."""
    if _process is None:
        return
    try:
        _process.stdin.write(command + "\n")
    except OSError:   # BrokenPipeError and friends: nobody is reading the other end any more
        logger.warning(f"Ducking off: the helper has gone (couldn't send {command!r}).")
        _stop()
        return

    reply = _read_line(_process, REPLY_TIMEOUT)
    if reply is None:
        logger.warning(f"Ducking off: no reply from the helper to {command!r}.")
        _stop()
    elif reply != "ok":
        logger.warning(f"Ducker answered {command!r} with {reply!r}.")


def _stop() -> None:
    """Closes the helper's stdin so it tears down and audio returns to normal, then waits for it to exit."""
    global _process
    if _process is None:
        return
    process, _process = _process, None   # ducking is off from here on, even if the steps below fail
    try:
        process.stdin.close()            # the helper's readLine() gets nil: it tears down and exits
    except OSError:
        pass                             # it has already gone
    try:
        process.wait(timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()                   # stuck: force it. macOS removes its tap and aggregate device with it
        process.wait()


def _read_line(process: subprocess.Popen, timeout: float) -> str | None:
    """The helper's next stdout line without its newline, or None if it exited or nothing came within timeout."""
    readable, _, _ = select.select([process.stdout], [], [], timeout)
    if not readable:
        return None                               # timed out
    line = process.stdout.readline()
    return line.strip() if line else None         # "" means end of output: the helper exited
