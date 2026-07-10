"""Extract material references from .pcf particle definition files."""

from __future__ import annotations
import logging
import re

logger = logging.getLogger(__name__)

# 扫描 PCF 二进制中嵌入的 materials/ 路径
_MATERIAL_RE = re.compile(rb'materials[/\\][^\x00"]+\.vmt', re.IGNORECASE)
# 也匹配不带 materials/ 前缀的裸纹理名（出现在 material 操作符中）
_BARE_TEX_RE = re.compile(rb'(?:material|texture)\x00+([^\x00]+)', re.IGNORECASE)


def extract_pcf_dependencies(file_content: bytes) -> set[str]:
    try:
        deps: set[str] = set()
        for match in _MATERIAL_RE.finditer(file_content):
            path = match.group(0).decode("ascii", errors="replace").replace("\\", "/")
            deps.add(path)
        # 部分 PCF 的 material/texture 操作符使用不带前缀的裸纹理名
        for match in _BARE_TEX_RE.finditer(file_content):
            raw = match.group(1).decode("ascii", errors="replace").replace("\\", "/")
            if not raw.lower().endswith((".vmt", ".vtf")):
                raw += ".vmt"
            if not raw.lower().startswith("materials/"):
                raw = "materials/" + raw
            deps.add(raw)
        return deps
    except Exception as exc:
        logger.warning("Failed to parse PCF: %s", exc)
        return set()
