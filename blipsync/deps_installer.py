"""Auto-install onnxruntime into Blender's bundled Python."""

from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import bpy

_STATUS = "idle"  # idle | installing | ok | failed
_ERROR: Optional[str] = None
_IMPORT_ERROR: Optional[str] = None
_PROGRESS = ""
_STEP_INDEX = 0
_STEP_STARTED = 0.0
_PROC: Optional[subprocess.Popen] = None
_LOG_HANDLE = None
_LOG_PATH: Optional[Path] = None
_POLL_TIMER = None
_REDRAW_TIMER = None
_AUTO_SCHEDULED = False

STEP_TIMEOUT_SEC = 1800


_STEPS: list[tuple[str, list[str]]] = [
    ("onnxruntime (CPU)", ["onnxruntime"]),
]


def _pip_packages_dir() -> Path:
    from .vendor import pip_packages_dir

    return pip_packages_dir()


def _marker_path() -> Path:
    config_dir = Path(bpy.utils.user_resource("CONFIG", path="blipsync"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "emotion_deps_ok"


def _log_path() -> Path:
    config_dir = Path(bpy.utils.user_resource("CONFIG", path="blipsync"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "emotion_deps_install.log"


def get_install_log_path() -> str:
    return str(_log_path())


def get_install_status() -> str:
    if _STATUS in ("idle", "ok") and onnxruntime_importable():
        return "ok"
    return _STATUS


def get_install_error() -> Optional[str]:
    return _ERROR or _IMPORT_ERROR


def get_import_error() -> Optional[str]:
    return _IMPORT_ERROR


def get_install_progress() -> str:
    return _PROGRESS


def is_installing() -> bool:
    return _STATUS == "installing"


def _log(msg: str) -> None:
    line = f"[bAnima deps] {msg}"
    print(line)
    log_file = _LOG_PATH or _log_path()
    try:
        with log_file.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _discover_pip_locations(*packages: str) -> list[str]:
    locations: list[str] = []
    for package in packages:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", package],
                capture_output=True,
                text=True,
                timeout=60,
                env=_pip_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if line.startswith("Location:"):
                loc = line.split(":", 1)[1].strip()
                if loc and loc not in locations:
                    locations.append(loc)
                    _log(f"pip show {package} -> {loc}")
    return locations


def _collect_site_paths() -> list[str]:
    import site

    paths: list[str] = []
    seen: set[str] = set()

    def _add(path: str | Path) -> None:
        if not path:
            return
        try:
            resolved = str(Path(path).resolve())
        except Exception:
            return
        if resolved in seen or not Path(resolved).is_dir():
            return
        seen.add(resolved)
        paths.append(resolved)

    _add(Path(sys.prefix) / "Lib" / "site-packages")
    for path in site.getsitepackages():
        _add(path)
    try:
        _add(site.getusersitepackages())
    except Exception:
        pass
    ver = f"Python{sys.version_info.major}{sys.version_info.minor}"
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        _add(Path(appdata) / "Python" / ver / "site-packages")
    for loc in _discover_pip_locations("onnxruntime"):
        _add(loc)
    from .vendor import pip_packages_dir, setup_pip_packages_path, setup_vendor_path, vendor_dir

    setup_pip_packages_path()
    _add(pip_packages_dir())
    setup_vendor_path()
    _add(vendor_dir())
    return paths


def refresh_python_path() -> None:
    import site

    importlib.invalidate_caches()
    for path in _collect_site_paths():
        if path not in sys.path:
            sys.path.insert(0, path)
        try:
            site.addsitedir(path)
        except Exception:
            pass
    _log(f"python={sys.executable}")
    _log(f"sys.path[0:3]={sys.path[:3]}")


def _purge_onnxruntime_modules() -> None:
    for name in list(sys.modules):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            del sys.modules[name]


def try_import_onnxruntime(*, refresh: bool = False) -> tuple[bool, str]:
    global _IMPORT_ERROR

    if refresh:
        refresh_python_path()
    else:
        importlib.invalidate_caches()

    from .vendor import setup_pip_packages_path, setup_vendor_path

    setup_pip_packages_path()
    setup_vendor_path()
    _purge_onnxruntime_modules()

    try:
        import onnxruntime

        location = getattr(onnxruntime, "__file__", "") or "unknown"
        _IMPORT_ERROR = None
        _log(f"import onnxruntime OK: {location}")
        return True, location
    except Exception as exc:
        _IMPORT_ERROR = str(exc)
        _log(f"import onnxruntime FAILED: {exc}")
        return False, str(exc)


def onnxruntime_importable(*, refresh: bool = False) -> bool:
    ok, _detail = try_import_onnxruntime(refresh=refresh)
    return ok


def speechbrain_importable(*, refresh: bool = False) -> bool:
    """Deprecated alias."""
    return onnxruntime_importable(refresh=refresh)


def try_import_speechbrain(*, refresh: bool = False) -> tuple[bool, str]:
    """Deprecated alias."""
    return try_import_onnxruntime(refresh=refresh)


def verify_emotion_deps() -> tuple[bool, str]:
    global _ERROR
    try:
        ok, detail = try_import_onnxruntime(refresh=True)
        if not ok:
            _ERROR = detail
            return False, f"onnxruntime import failed:\n{detail}"
        from .emotion_engine import get_classifier_error, is_classifier_available, reset_classifier_state

        reset_classifier_state()
        if is_classifier_available():
            _ERROR = None
            return True, detail
        err = get_classifier_error()
        _ERROR = err
        return False, err or "onnxruntime loaded but emotion model failed to initialize."
    except Exception as exc:
        _ERROR = str(exc)
        return False, str(exc)


def _ensure_pip() -> None:
    if importlib.util.find_spec("pip") is None:
        _log("ensurepip...")
        subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])


def _pip_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_PROGRESS_BAR"] = "off"
    return env


def _start_step(step_index: int) -> None:
    global _PROC, _LOG_HANDLE, _STEP_STARTED, _PROGRESS

    label, args = _STEPS[step_index]
    _STEP_STARTED = time.monotonic()
    _PROGRESS = f"Step {step_index + 1}/{len(_STEPS)}: {label}"
    _log(f"START {_PROGRESS}")

    target_dir = _pip_packages_dir()
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-input",
        "--no-warn-script-location",
        "--upgrade",
        "--target",
        str(target_dir),
        *args,
    ]
    _log(f"target={target_dir}")
    _log("CMD: " + " ".join(cmd))

    log_file = _LOG_PATH or _log_path()
    _LOG_HANDLE = log_file.open("a", encoding="utf-8", errors="replace")
    _LOG_HANDLE.write(f"\n--- {_PROGRESS} ---\n")
    _LOG_HANDLE.flush()

    _PROC = subprocess.Popen(
        cmd,
        stdout=_LOG_HANDLE,
        stderr=subprocess.STDOUT,
        env=_pip_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _finish_success() -> None:
    global _STATUS, _ERROR, _PROC, _PROGRESS

    _close_proc_handles()
    _PROC = None
    _marker_path().write_text("ok", encoding="utf-8")
    _STATUS = "ok"
    _ERROR = None
    _PROGRESS = "Complete"
    _log("INSTALL OK")
    _stop_poll_timer()
    _stop_redraw_timer()

    ok, msg = verify_emotion_deps()
    if ok:
        _log("verify OK")
    else:
        _log(f"post-install verify: {msg}")

    def _deferred_verify() -> None:
        verify_emotion_deps()
        _tag_ui_redraw()
        return None

    bpy.app.timers.register(_deferred_verify, first_interval=0.5)
    _tag_ui_redraw()


def _finish_failure(message: str) -> None:
    global _STATUS, _ERROR, _PROC, _PROGRESS

    _close_proc_handles()
    _PROC = None
    _STATUS = "failed"
    _ERROR = message
    _PROGRESS = "Failed"
    _log(f"INSTALL FAILED: {message}")
    _stop_poll_timer()
    _stop_redraw_timer()
    _tag_ui_redraw()


def _close_proc_handles() -> None:
    global _LOG_HANDLE
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.close()
        except Exception:
            pass
        _LOG_HANDLE = None


def _poll_install() -> Optional[float]:
    global _STEP_INDEX, _PROC, _PROGRESS

    if _STATUS != "installing":
        return None

    if _PROC is None:
        if _STEP_INDEX >= len(_STEPS):
            _finish_success()
            return None
        try:
            _start_step(_STEP_INDEX)
        except Exception as exc:
            _finish_failure(str(exc))
        return 1.0

    elapsed = time.monotonic() - _STEP_STARTED
    if elapsed > STEP_TIMEOUT_SEC:
        try:
            _PROC.kill()
        except Exception:
            pass
        _finish_failure(
            f"Timeout ({STEP_TIMEOUT_SEC // 60} min) at step {_STEP_INDEX + 1}. "
            f"See log: {_log_path()}"
        )
        return None

    code = _PROC.poll()
    if code is None:
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        label = _STEPS[_STEP_INDEX][0]
        _PROGRESS = f"Step {_STEP_INDEX + 1}/{len(_STEPS)}: {label} ({mins}:{secs:02d})"
        return 1.0

    _close_proc_handles()
    _PROC = None

    if code != 0:
        tail = ""
        try:
            log_file = _LOG_PATH or _log_path()
            if log_file.exists():
                tail = log_file.read_text(encoding="utf-8", errors="replace")[-1500:]
        except Exception:
            pass
        _finish_failure(f"pip exit {code} at step {_STEP_INDEX + 1}.\n{tail}")
        return None

    _log(f"Step {_STEP_INDEX + 1} done")
    _STEP_INDEX += 1
    if _STEP_INDEX >= len(_STEPS):
        _finish_success()
        return None
    return 0.5


def _tag_ui_redraw() -> None:
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _poll_redraw() -> Optional[float]:
    if _STATUS != "installing":
        return None
    _tag_ui_redraw()
    return 1.0


def _start_poll_timer() -> None:
    global _POLL_TIMER
    _stop_poll_timer()
    _POLL_TIMER = bpy.app.timers.register(_poll_install, first_interval=0.5)


def _stop_poll_timer() -> None:
    global _POLL_TIMER
    if _POLL_TIMER is None:
        return
    try:
        bpy.app.timers.unregister(_POLL_TIMER)
    except Exception:
        pass
    _POLL_TIMER = None


def _start_redraw_timer() -> None:
    global _REDRAW_TIMER
    _stop_redraw_timer()
    _REDRAW_TIMER = bpy.app.timers.register(_poll_redraw, first_interval=1.0)


def _stop_redraw_timer() -> None:
    global _REDRAW_TIMER
    if _REDRAW_TIMER is None:
        return
    try:
        bpy.app.timers.unregister(_REDRAW_TIMER)
    except Exception:
        pass
    _REDRAW_TIMER = None


def start_install(*, force: bool = False) -> str:
    global _STATUS, _ERROR, _STEP_INDEX, _PROGRESS, _LOG_PATH, _IMPORT_ERROR

    if _STATUS == "installing":
        return "installing"
    if not force and onnxruntime_importable(refresh=True):
        _STATUS = "ok"
        _ERROR = None
        return "ok"

    if force:
        marker = _marker_path()
        if marker.exists():
            marker.unlink()
        _IMPORT_ERROR = None
        from .emotion_engine import reset_classifier_state

        reset_classifier_state()

    try:
        _ensure_pip()
    except Exception as exc:
        _STATUS = "failed"
        _ERROR = str(exc)
        return "failed"

    _LOG_PATH = _log_path()
    _LOG_PATH.write_text(f"Install started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    _STEP_INDEX = 0
    _PROGRESS = "Starting..."
    _STATUS = "installing"
    _ERROR = None
    _log("Install queued")
    _start_poll_timer()
    _start_redraw_timer()
    return "installing"


def schedule_auto_install() -> None:
    global _AUTO_SCHEDULED, _STATUS, _ERROR

    if _AUTO_SCHEDULED:
        return
    _AUTO_SCHEDULED = True

    def _deferred() -> None:
        if onnxruntime_importable(refresh=True):
            _STATUS = "ok"
            verify_emotion_deps()
        elif _marker_path().exists():
            _STATUS = "ok"
            verify_emotion_deps()
        else:
            start_install(force=False)
        _tag_ui_redraw()
        return None

    bpy.app.timers.register(_deferred, first_interval=1.0)


def reset_install_state() -> None:
    global _STATUS, _ERROR, _AUTO_SCHEDULED, _STEP_INDEX, _PROGRESS, _PROC, _IMPORT_ERROR
    _stop_poll_timer()
    _stop_redraw_timer()
    if _PROC is not None:
        try:
            _PROC.kill()
        except Exception:
            pass
    _close_proc_handles()
    _PROC = None
    _STATUS = "idle"
    _ERROR = None
    _IMPORT_ERROR = None
    _AUTO_SCHEDULED = False
    _STEP_INDEX = 0
    _PROGRESS = ""
    marker = _marker_path()
    if marker.exists():
        marker.unlink()
