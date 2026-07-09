"""Skill Registry — 技能注册与加载"""

from pathlib import Path
from typing import Dict, List, Optional

from src.config import ROOT_DIR

SKILLS_DIR = ROOT_DIR / "skills"
SEP = chr(10)


def _parse_frontmatter(text: str) -> tuple:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, parts[2].strip()


def scan_skills() -> List[Dict]:
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "SKILL.md"
        if not manifest.exists():
            continue
        raw = manifest.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        name = meta.get("name", d.name)
        first_line = body.split(SEP)[0].lstrip("#").strip()[:80]
        desc = meta.get("description", first_line)
        skills.append({"name": name, "description": desc, "path": str(d)})
    return skills


def load_skill(name: str) -> Optional[str]:
    for s in scan_skills():
        if s["name"] == name:
            path = Path(s["path"]) / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
    return None


def get_skill_index() -> str:
    skills = scan_skills()
    if not skills:
        return ""
    lines = ["Available skills:"]
    for s in skills:
        lines.append(f"- {s['name']}: {s['description']}")
    lines.append("Use /skill <name> <task> to invoke.")
    return SEP.join(lines)
