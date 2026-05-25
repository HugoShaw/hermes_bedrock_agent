"""LibreOffice UNO connection management.

Must be called with /usr/bin/python3 — UNO bindings are NOT available in venvs.
"""

from __future__ import annotations

import subprocess
import time
from typing import Any


def connect(host: str = "localhost", port: int = 2002) -> Any:
    """Connect to a running headless LibreOffice instance.

    Returns the com.sun.star.frame.Desktop object.
    Raises RuntimeError if the connection fails.
    """
    try:
        import uno  # noqa: F401 — UNO only available with system python3
        from com.sun.star.beans import PropertyValue  # noqa: F401

        local_ctx = uno.getComponentContext()
        resolver = local_ctx.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_ctx
        )
        ctx = resolver.resolve(
            f"uno:socket,host={host},port={port};urp;StarOffice.ComponentContext"
        )
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        return desktop
    except ImportError as e:
        raise RuntimeError(
            "UNO bindings not found. Run with /usr/bin/python3, not a venv Python."
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"Could not connect to LibreOffice at {host}:{port}. "
            "Make sure LibreOffice is running:\n"
            "  soffice --headless --invisible --nocrashreport --nodefault "
            f'--nofirststartwizard "--accept=socket,host={host},port={port};urp;StarOffice.ServiceManager" &'
        ) from e


def ensure_soffice_running(host: str = "localhost", port: int = 2002, wait: float = 8.0) -> None:
    """Start a headless LibreOffice listener if one is not already reachable."""
    try:
        connect(host, port)
        return
    except RuntimeError:
        pass

    cmd = [
        "soffice",
        "--headless", "--invisible",
        "--nocrashreport", "--nodefault", "--nofirststartwizard",
        f"--accept=socket,host={host},port={port};urp;StarOffice.ServiceManager",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(wait)


def open_document(desktop: Any, path: str) -> Any:
    """Open an ODS/XLSX document hidden (no UI)."""
    import uno
    from com.sun.star.beans import PropertyValue

    file_url = uno.systemPathToFileUrl(path)
    open_props = (
        PropertyValue(Name="Hidden", Value=True),
        PropertyValue(Name="MacroExecutionMode", Value=0),
    )
    doc = desktop.loadComponentFromURL(file_url, "_blank", 0, open_props)
    if doc is None:
        raise RuntimeError(f"LibreOffice failed to open: {path}")
    return doc
