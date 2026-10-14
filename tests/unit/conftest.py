"""Load the integration's pure modules (report, github, const) without importing Home Assistant."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

PACKAGE = Path(__file__).resolve().parents[2] / "custom_components" / "fenton_feedback"

if "fenton_feedback" not in sys.modules:
    package = types.ModuleType("fenton_feedback")
    package.__path__ = [str(PACKAGE)]
    sys.modules["fenton_feedback"] = package
    for name in ("const", "report", "github"):
        spec = importlib.util.spec_from_file_location(f"fenton_feedback.{name}", PACKAGE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
