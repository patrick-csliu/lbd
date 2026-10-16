"""MkDocs hooks for the LBD documentation.

- Shows the release version in the site name (from scripts/check_versions.py).
- Replaces {{ style_table("FigureStyle") }} in a page with a table of that style group's
  settings (type, default, allowed values, description), generated from lbd.plot.style, so the
  documentation can never disagree with the code.
"""

import importlib.util
import logging
import re
import sys
import typing
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
log = logging.getLogger("mkdocs.plugins.lbd")
_TABLE = re.compile(r'(?<!`)\{\{\s*style_table\(\s*"(\w+)"\s*\)\s*\}\}(?!`)')  # not in `code`


def _release_version() -> str:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))  # check_versions imports its sibling `languages`
    spec = importlib.util.spec_from_file_location("lbd_check_versions", SCRIPTS / "check_versions.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.release_version()
    except mod.VersionError as e:
        # A warning fails `mkdocs build --strict`, so a release can't ship mismatched versions.
        log.warning(f"{e}\nThe documentation shows the version as 'dev'.")
        return "dev"


def on_config(config, **kwargs):
    version = _release_version()
    config["site_name"] = f"LBD {version}"
    config["extra"]["version"] = version
    return config


# ---- style tables ---------------------------------------------------------------------


def _type_and_allowed(annotation):
    """(type text, allowed text) for a field annotation."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    nullable = False
    if origin is typing.Union and type(None) in args:
        nullable = True
        annotation = next(a for a in args if a is not type(None))
        origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Literal:
        return "text", ", ".join(f"`{a}`" for a in args)
    name = {bool: "yes/no", int: "integer", float: "number", str: "text"}.get(annotation)
    if name is None:
        if origin in (list, typing.List):
            name = "list of colours"
        elif origin in (dict, typing.Dict):
            name = "object"
        else:
            name = getattr(annotation, "__name__", str(annotation))
    return (name + (" or empty" if nullable else "")), ""


def _limits(field):
    parts = []
    for m in field.metadata:
        for attr, sym in (("gt", ">"), ("ge", "≥"), ("lt", "<"), ("le", "≤")):
            v = getattr(m, attr, None)
            if v is not None:
                parts.append(f"{sym} {v:g}" if isinstance(v, (int, float)) else f"{sym} {v}")
    return ", ".join(parts)


def _default(field):
    d = field.get_default(call_default_factory=True)
    if d is None:
        return "*automatic*"
    if isinstance(d, bool):
        return "yes" if d else "no"
    if isinstance(d, str):
        return f'`"{d}"`' if d else '`""`'
    if isinstance(d, (list, dict)) and not d:
        return "`{}`" if isinstance(d, dict) else "`[]`"
    if isinstance(d, list):
        return "see below" if len(d) > 3 else f"`{d}`"
    return f"`{d:g}`" if isinstance(d, float) else f"`{d}`"


def style_table(model_name: str) -> str:
    """A Markdown table of a style model's settings (name, type, default, allowed, meaning)."""
    from pydantic import BaseModel

    from lbd.plot import style as st

    model = getattr(st, model_name, None)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise ValueError(f"style_table: {model_name!r} is not a style model in lbd.plot.style")
    rows = ["| Setting | Type | Default | Allowed | Meaning |", "|---|---|---|---|---|"]
    for name, field in model.model_fields.items():
        ann = field.annotation
        sub = [a for a in (typing.get_args(ann) or (ann,)) if isinstance(a, type) and issubclass(a, BaseModel)]
        desc = (field.description or "").replace("|", "\\|")
        if sub:
            rows.append(f"| `{name}` | group | | | {desc} → *{sub[0].__name__}* |")
            continue
        typ, allowed = _type_and_allowed(ann)
        limits = _limits(field)
        allowed = ", ".join(x for x in (allowed, limits) if x)
        rows.append(f"| `{name}` | {typ} | {_default(field)} | {allowed} | {desc} |")
    return "\n".join(rows)


def on_page_markdown(markdown, page, config, files, **kwargs):
    if "style_table(" not in markdown:
        return markdown
    return _TABLE.sub(lambda m: style_table(m.group(1)), markdown)
