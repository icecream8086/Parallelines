"""Standalone worker for parallel dependency extraction. Must be picklable.

Uses the "pre-read + pure parse" approach (parser-audit-fix.md sect;10.8):
workers receive pre-read file content as bytes and run only parsers, never
opening VPKs or filesystem chains.
"""

from __future__ import annotations

from parallelines.error_policy import parse_failure

# Existing parsers (always available).
from parallelines.parsers.vmt_parser import extract_vmt_dependencies
from parallelines.parsers.nut_parser import extract_nut_dependencies
from parallelines.parsers.manifest_parser import is_manifest_path

# Lazy imports for new parsers (parser-audit-fix.md ss1-2).
try:
    from parallelines.parsers.game_sounds_parser import extract_game_sounds_dependencies

    HAS_GAME_SOUNDS = True
except ImportError:
    HAS_GAME_SOUNDS = False

try:
    from parallelines.parsers.soundscapes_parser import extract_soundscapes_dependencies

    HAS_SOUNDSCAPES = True
except ImportError:
    HAS_SOUNDSCAPES = False

try:
    from parallelines.parsers.level_sounds_parser import extract_level_sounds_dependencies

    HAS_LEVEL_SOUNDS = True
except ImportError:
    HAS_LEVEL_SOUNDS = False

try:
    from parallelines.parsers.population_parser import extract_population_dependencies

    HAS_POPULATION = True
except ImportError:
    HAS_POPULATION = False

try:
    from parallelines.parsers.melee_parser import extract_melee_dependencies

    HAS_MELEE = True
except ImportError:
    HAS_MELEE = False

try:
    from parallelines.parsers.missions_parser import extract_missions_dependencies

    HAS_MISSIONS = True
except ImportError:
    HAS_MISSIONS = False

try:
    from parallelines.parsers.pcf_parser import extract_pcf_dependencies

    HAS_PCF = True
except ImportError:
    HAS_PCF = False

try:
    from parallelines.parsers.res_parser import extract_res_dependencies

    HAS_RES = True
except ImportError:
    HAS_RES = False

try:
    from parallelines.parsers.weapon_parser import extract_weapon_dependencies

    HAS_WEAPON = True
except ImportError:
    HAS_WEAPON = False

try:
    from parallelines.parsers.nuc_parser import extract_nuc_dependencies

    HAS_NUC = True
except ImportError:
    HAS_NUC = False

try:
    from parallelines.parsers.ani_parser import extract_ani_dependencies

    HAS_ANI = True
except ImportError:
    HAS_ANI = False

try:
    from parallelines.parsers.texture_list_parser import extract_texture_list_dependencies

    HAS_TEXTURE_LIST = True
except ImportError:
    HAS_TEXTURE_LIST = False

try:
    from parallelines.parsers.simple_list_parser import parse_simple_list

    HAS_SIMPLE_LIST = True
except ImportError:
    HAS_SIMPLE_LIST = False


def _parse_simple_list(text: str, prefix: str = "") -> set[str]:
    """Parse a simple line-based list (one resource path per line, no KeyValues).

    Falls back to inline implementation when ``simple_list_parser`` is unavailable.
    """
    if HAS_SIMPLE_LIST:
        return parse_simple_list(text, prefix)
    deps: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#")):
            continue
        path = stripped.replace("\\", "/")
        if prefix and not path.lower().startswith(prefix.lower()):
            path = prefix + path
        deps.add(path)
    return deps


def _dispatch_txt(virtual_path: str, content: bytes) -> set[str]:
    """Classify .txt file by path pattern and run the appropriate parser."""
    lower = virtual_path.lower()
    text = content.decode("utf-8", errors="replace")

    if is_manifest_path(virtual_path):
        deps: set[str] = set()
        for line in text.splitlines():
            s = line.strip()
            if s and not s.startswith(("//", "#")):
                deps.add(s)
        return deps
    if "game_sounds" in lower and HAS_GAME_SOUNDS:
        return extract_game_sounds_dependencies(text)
    if "soundscapes" in lower and HAS_SOUNDSCAPES:
        return extract_soundscapes_dependencies(text)
    if lower.endswith("_level_sounds.txt") and HAS_LEVEL_SOUNDS:
        return extract_level_sounds_dependencies(text)
    if lower.endswith("population.txt") and HAS_POPULATION:
        return extract_population_dependencies(text)
    if lower.startswith("missions/") and HAS_MISSIONS:
        return extract_missions_dependencies(text)
    if lower.startswith("scripts/melee/") and HAS_MELEE:
        return extract_melee_dependencies(text)
    if lower.startswith("scripts/weapon_") and "manifest" not in lower and HAS_WEAPON:
        return extract_weapon_dependencies(text)
    if lower in ("scripts/hud_textures.txt", "scripts/mod_textures.txt") and HAS_TEXTURE_LIST:
        return extract_texture_list_dependencies(text)
    if lower.endswith("sound_prefetch.txt"):
        return _parse_simple_list(text, prefix="sound/")
    if lower.endswith("level_sounds_general.txt") and HAS_LEVEL_SOUNDS:
        return extract_level_sounds_dependencies(text)
    if lower in ("scripts/soundmixers.txt", "scripts/propdata.txt"):
        return _parse_kv_sound_deps(text)
    return set()


def _dispatch_parse(virtual_path: str, ext: str, content: bytes) -> set[str]:
    """Classify file by extension and run the appropriate parser."""
    if ext == ".vmt":
        text = content.decode("utf-8", errors="replace")
        return extract_vmt_dependencies(text)
    if ext == ".nut":
        text = content.decode("utf-8", errors="replace")
        return extract_nut_dependencies(text)
    if ext == ".txt":
        return _dispatch_txt(virtual_path, content)
    if ext == ".res" and HAS_RES:
        text = content.decode("utf-8", errors="replace")
        return extract_res_dependencies(text)
    if ext == ".pcf" and HAS_PCF:
        return extract_pcf_dependencies(content)
    if ext == ".nuc" and HAS_NUC:
        return extract_nuc_dependencies(content)
    if ext == ".ani" and HAS_ANI:
        text = content.decode("utf-8", errors="replace")
        return extract_ani_dependencies(text)
    return set()


def _parse_kv_sound_deps(text: str) -> set[str]:
    """Extract .wav / .phy references from KV-format soundmixers.txt / propdata.txt.

    Matches the logic in GraphBuilder._extract_kv_sound_deps.
    """
    deps: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "{")):
            continue
        for token in stripped.split('"'):
            token = token.strip().replace("\\", "/")
            if token.lower().endswith((".wav", ".phy")):
                if token.lower().endswith(".wav") and not token.lower().startswith("sound/"):
                    token = "sound/" + token
                deps.add(token)
    return deps


def extract_deps_worker(task: tuple) -> list[tuple[str, list[str]]]:
    """Process a chunk of pre-read file content and return extracted deps.

    Args:
        task: A tuple ``(chunk_items,)`` where *chunk_items* is a list of
              ``(virtual_path, ext, content_bytes)`` triples.

    Returns:
        List of ``(virtual_path, [dep1, dep2, ...])`` for files where deps
        were found.
    """
    chunk = task[0] if isinstance(task, tuple) and len(task) == 1 else task
    results: list[tuple[str, list[str]]] = []
    for virtual_path, ext, content in chunk:
        try:
            deps = _dispatch_parse(virtual_path, ext, content)
            if deps:
                results.append((virtual_path, list(deps)))
        except Exception as exc:
            parse_failure(exc, "worker.extract_deps")
            continue
    return results


# Alias for builder.py's build_parallel import path.
parse_file_worker = extract_deps_worker
