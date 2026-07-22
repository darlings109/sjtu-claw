"""Skill Registry — 技能注册与加载

两级设计（参考 LCC s07）：
  第一级：catalog（名称 + 描述），启动时注入 system prompt
  第二级：content（完整 SKILL.md），Agent 通过 load_skill tool 按需加载
"""

from pathlib import Path
from typing import Dict, List, Optional

from src.config import ROOT_DIR

SKILLS_DIR = ROOT_DIR / "skills"
SEP = chr(10)

# 技能内容缓存（运行时常驻）
_SKILLS_CACHE: Dict[str, dict] = {}


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


def _scan_and_cache() -> None:
    """扫描 skills/ 目录并填充 _SKILLS_CACHE"""
    _SKILLS_CACHE.clear()
    if not SKILLS_DIR.exists():
        return
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
        _SKILLS_CACHE[name] = {
            "name": name,
            "description": desc,
            "content": raw,
            "path": str(d),
        }


def scan_skills() -> List[Dict]:
    """返回所有技能元数据列表（兼容旧接口）"""
    if not _SKILLS_CACHE:
        _scan_and_cache()
    return [
        {"name": info["name"], "description": info["description"], "path": info["path"]}
        for info in _SKILLS_CACHE.values()
    ]


def load_skill(name: str) -> Optional[str]:
    """按名称加载技能完整 content（用于 /skill 命令，兼容旧接口）"""
    if not _SKILLS_CACHE:
        _scan_and_cache()
    info = _SKILLS_CACHE.get(name)
    if info:
        return info["content"]
    return None


def load_skill_content(name: str) -> str:
    """按名称加载技能完整 content（供 load_skill tool 调用）"""
    if not _SKILLS_CACHE:
        _scan_and_cache()
    info = _SKILLS_CACHE.get(name)
    if not info:
        return f"Skill not found: {name}"
    return info["content"]


def get_skill_catalog() -> str:
    """生成简短技能目录（第一级：~100 tokens/skill，注入 system prompt）"""
    if not _SKILLS_CACHE:
        _scan_and_cache()
    if not _SKILLS_CACHE:
        return ""
    lines = ["Available skills:"]
    for info in _SKILLS_CACHE.values():
        lines.append(f"- {info['name']}: {info['description']}")
    lines.append("Use load_skill to get full details when needed.")
    return SEP.join(lines)


def get_skill_index() -> str:
    """生成带 /skill 命令说明的技能索引（兼容旧接口）"""
    if not _SKILLS_CACHE:
        _scan_and_cache()
    if not _SKILLS_CACHE:
        return ""
    lines = ["Available skills:"]
    for info in _SKILLS_CACHE.values():
        lines.append(f"- {info['name']}: {info['description']}")
    lines.append("Use /skill <name> <task> to invoke.")
    return SEP.join(lines)


def create_skill(name: str, content: str) -> bool:
    """创建新技能目录 + SKILL.md

    Args:
        name: 技能名称（目录名）
        content: SKILL.md 完整内容

    Returns:
        True 成功 / False 已存在
    """
    target = SKILLS_DIR / name
    if target.exists():
        return False
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(content, encoding="utf-8")
    _scan_and_cache()
    return True


def delete_skill(name: str) -> bool:
    """删除技能目录及 SKILL.md"""
    from shutil import rmtree
    target = SKILLS_DIR / name
    if not target.exists() or not target.is_dir():
        return False
    rmtree(target)
    _scan_and_cache()
    return True


def update_skill(name: str, content: str) -> bool:
    """更新已有技能的 SKILL.md 内容"""
    target = SKILLS_DIR / name
    manifest = target / "SKILL.md"
    if not target.exists() or not manifest.exists():
        return False
    manifest.write_text(content, encoding="utf-8")
    _scan_and_cache()
    return True


# 模块加载时扫描一次
_scan_and_cache()
