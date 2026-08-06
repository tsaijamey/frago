"""Windows Smart App Control detection.

Smart App Control admits only signed or cloud-reputable executables. Everything
it refuses, it refuses in a way frago cannot observe: a hook binary that will
not load produces no output, and the agent carries on without the routing frago
was supposed to supply. The user gets a frago that starts cleanly and quietly
does half its job — the worst failure shape there is, because nothing in the
logs says anything is wrong.

Detection does not fix that. Smart App Control has no exclusion list, and the
launcher uv generates is unsigned by construction: its bytes embed the absolute
path of the target interpreter, so its hash differs on every machine and cloud
reputation can never accumulate. What detection can do is turn a silent failure
into a stated one.
"""

from __future__ import annotations

import platform

# HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy — written by Windows itself.
_CI_POLICY_KEY = r"SYSTEM\CurrentControlSet\Control\CI\Policy"
_CI_POLICY_VALUE = "VerifiedAndReputablePolicyState"

SAC_OFF = 0
SAC_ENFORCING = 1
SAC_EVALUATION = 2  # audits without blocking


def smart_app_control_state() -> int | None:
    """Return the Smart App Control policy state, or None when unknown.

    None covers every case where the question does not apply or cannot be
    answered: a non-Windows host, a Windows build predating the feature (the
    value is simply absent), or a registry read that is refused. All three mean
    the same thing to callers — there is nothing to warn about.
    """
    if platform.system().lower() != "windows":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - only reachable off Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _CI_POLICY_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _CI_POLICY_VALUE)
    except OSError:
        return None
    return value if isinstance(value, int) else None


def smart_app_control_warning() -> str | None:
    """Return a warning worth showing the user, or None when there is none.

    Only the enforcing state earns one. Evaluation mode audits without blocking,
    so warning there would cry wolf — it may promote itself to enforcing later,
    but that is not a problem the user has yet.
    """
    if smart_app_control_state() != SAC_ENFORCING:
        return None
    return (
        "Windows Smart App Control is on. It blocks unsigned executables — "
        "the frago hook binary and the launcher uv generates are both "
        "unsigned — and it blocks them silently: hooks stop routing without "
        "reporting an error, so frago looks healthy while doing half its job.\n"
        "Turn it off under Windows Security > App & browser control > Smart "
        "App Control, then restart. Windows presents that switch as permanent "
        "and may refuse to re-enable it without a reset, so decide before "
        "flipping it.\n"
        "Blocks already recorded are in Event Viewer under "
        "Microsoft-Windows-CodeIntegrity/Operational."
    )
