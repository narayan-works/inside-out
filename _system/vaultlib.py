"""Shared helpers for inside-out vault scripts (note IO, dates, links)."""
import datetime as dt
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("PyYAML missing: pip install --user --break-system-packages pyyaml")

VAULT = Path(__file__).resolve().parent.parent
# Segments come from the keys of `half_life_days` in _system/config.yaml.
SEGMENTS = None  # filled in after load_config is defined
FM_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def read_note(path):
    """Return (frontmatter dict, body str). frontmatter None if missing/malformed."""
    text = Path(path).read_text(encoding="utf-8")
    m = FM_RE.match(text)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None, text
    if not isinstance(fm, dict):
        return None, text
    return fm, m.group(2)


def dump_note(fm, body):
    y = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000, default_flow_style=False)
    return "---\n" + y + "---\n" + body


def write_note(path, fm, body):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dump_note(fm, body), encoding="utf-8")


def link_name(x):
    """'[[Foo|bar]]' or 'Foo' -> 'Foo'."""
    if x is None:
        return ""
    s = str(x).strip()
    m = LINK_RE.search(s)
    return (m.group(1) if m else s).strip()


def as_list(x):
    if x is None or x == "":
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return s[:60]


def parse_when(x, default_hour=12):
    """Accept date, datetime, or common ISO-ish strings. Returns naive local datetime or None."""
    if x is None or x == "":
        return None
    if isinstance(x, dt.datetime):
        return x.replace(tzinfo=None)
    if isinstance(x, dt.date):
        return dt.datetime(x.year, x.month, x.day, default_hour)
    s = str(x).strip().replace("/", "-")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        d = dt.date.fromisoformat(s[:10])
        return dt.datetime(d.year, d.month, d.day, default_hour)
    except ValueError:
        return None


def parse_day(x):
    w = parse_when(x)
    return w.date() if w else None


def replace_block(body, name, content):
    """Replace text between <!-- {name}:start --> and <!-- {name}:end -->, appending markers if absent."""
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    block = f"{start}\n{content.rstrip()}\n{end}"
    if start in body and end in body:
        pre = body.split(start, 1)[0]
        post = body.split(end, 1)[1]
        return pre + block + post
    return body.rstrip() + "\n\n" + block + "\n"


def load_config():
    cfg_path = VAULT / "_system" / "config.yaml"
    return yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}


SEGMENTS = list((load_config().get("half_life_days") or {}).keys()) or ["core", "experiments"]
