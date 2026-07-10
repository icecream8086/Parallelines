"""Shared path normalisation helpers for Source Engine resource paths."""

from __future__ import annotations


def normalise_sound_path(raw: str) -> str:
    """Normalise a sound path: strip, backslash→slash, prepend ``sound/`` if missing."""
    path = raw.strip().replace("\\", "/")
    if not path.lower().startswith("sound/"):
        path = "sound/" + path
    return path


def normalise_texture_path(raw: str) -> str:
    """Normalise a texture path: strip, backslash→slash, append ``.vtf`` if no extension,
    prepend ``materials/`` if neither ``materials/`` nor ``resource/``."""
    path = raw.strip().replace("\\", "/")
    if not path.endswith((".vtf", ".vmt", ".png", ".ttf", ".tga")):
        path += ".vtf"
    if not (path.lower().startswith("materials/") or path.lower().startswith("resource/")):
        path = "materials/" + path
    return path
