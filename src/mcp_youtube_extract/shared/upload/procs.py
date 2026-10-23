"""Is a process still running? Used to tell live locks and jobs from leftovers."""

import os


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OverflowError, ValueError):
        return False
    return True
