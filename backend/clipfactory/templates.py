"""Data-driven editing templates.

Built-in templates live in ``templates/*.json`` (repository). User templates live in
``<data>/templates/*.json`` and can be created/edited from the UI; a user template with the same
id as a built-in one overrides it. Every template is validated before use.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import NotFoundError, ValidationError

REQUIRED: dict[str, dict[str, tuple[float, float]]] = {
    "duration": {"target": (5, 90)},
    "pacing": {"min_cut": (0.4, 10), "max_cut": (0.6, 15), "max_static_seconds": (1, 30)},
    "zoom": {"intensity": (0, 0.6), "every_n_cuts": (0, 20), "ramp": (0.05, 2), "hold": (0.1, 5)},
    "sfx": {"density": (0, 1), "volume": (0, 2)},
    "music": {"volume": (0, 2), "duck_to": (0, 1), "fade_in": (0, 10), "fade_out": (0, 10)},
    "captions": {"size": (20, 200), "stroke_width": (0, 20), "shadow": (0, 20), "max_words": (1, 8), "margin_v": (0, 1800)},
    "transitions": {"fade_in": (0, 3), "fade_out": (0, 3)},
}
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_template(t: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not re.match(r"^[a-z0-9_\-]{2,50}$", str(t.get("id", ""))):
        errors.append("id must be 2–50 chars of lowercase letters, digits, _ or -")
    if not str(t.get("name", "")).strip():
        errors.append("name is required")
    if t.get("fit") not in ("blur", "crop"):
        errors.append("fit must be 'blur' or 'crop'")
    for section, fields in REQUIRED.items():
        sec = t.get(section)
        if not isinstance(sec, dict):
            errors.append(f"missing section '{section}'")
            continue
        for key, (lo, hi) in fields.items():
            v = sec.get(key)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(f"{section}.{key} must be a number")
            elif not lo <= v <= hi:
                errors.append(f"{section}.{key} must be between {lo} and {hi}")
    pac = t.get("pacing", {})
    if isinstance(pac.get("min_cut"), (int, float)) and isinstance(pac.get("max_cut"), (int, float)) and pac["min_cut"] >= pac["max_cut"]:
        errors.append("pacing.min_cut must be smaller than pacing.max_cut")
    cap = t.get("captions", {})
    for key in ("primary", "highlight", "stroke"):
        if not COLOR.match(str(cap.get(key, ""))):
            errors.append(f"captions.{key} must be a #RRGGBB colour")
    if cap.get("position") not in ("lower_third", "center", "top"):
        errors.append("captions.position must be lower_third, center or top")
    for key in ("hook", "cta", "title"):
        if not isinstance(t.get(key), dict):
            errors.append(f"missing section '{key}'")
    if errors:
        raise ValidationError("Template is invalid: " + "; ".join(errors), errors=errors)
    return t


def _load_dir(d: Path, builtin: bool) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            validate_template(t)
        except (json.JSONDecodeError, ValidationError):
            continue  # invalid files are skipped; list_templates reports them
        t["builtin"] = builtin
        out[t["id"]] = t
    return out


def list_templates(settings: Settings) -> list[dict[str, Any]]:
    templates = _load_dir(settings.templates_dir, True)
    for tid, t in _load_dir(settings.user_templates_dir, False).items():
        t["overrides_builtin"] = tid in templates
        templates[tid] = t
    return sorted(templates.values(), key=lambda t: (not t["builtin"], t["name"]))


def get_template(settings: Settings, template_id: str) -> dict[str, Any]:
    for t in list_templates(settings):
        if t["id"] == template_id:
            return t
    raise NotFoundError(f"Template '{template_id}' not found.")


def save_template(settings: Settings, template: dict[str, Any]) -> dict[str, Any]:
    t = {k: v for k, v in template.items() if k not in ("builtin", "overrides_builtin")}
    t.setdefault("version", 1)
    validate_template(t)
    path = settings.user_templates_dir / f"{t['id']}.json"
    path.write_text(json.dumps(t, indent=2), encoding="utf-8")
    return get_template(settings, t["id"])


def delete_template(settings: Settings, template_id: str) -> None:
    path = settings.user_templates_dir / f"{template_id}.json"
    if not path.is_file():
        raise ValidationError("Only user templates can be deleted (built-in templates are read-only; save a copy to customise).")
    path.unlink()
