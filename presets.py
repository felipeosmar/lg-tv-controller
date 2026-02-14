"""
Gerenciamento de presets/favoritos — cenários salvos para a TV.
Exemplo: "Filme" = Netflix + Volume 15 + Tela On
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PRESETS_FILE = Path(__file__).parent / "presets.json"

DEFAULT_PRESETS = [
    {
        "id": "filme",
        "name": "🎬 Filme",
        "icon": "bi-film",
        "actions": [
            {"type": "app", "app_id": "netflix"},
            {"type": "volume", "level": 15},
        ],
    },
    {
        "id": "youtube",
        "name": "📺 YouTube",
        "icon": "bi-youtube",
        "actions": [
            {"type": "app", "app_id": "youtube.leanback.v4"},
            {"type": "volume", "level": 12},
        ],
    },
    {
        "id": "games",
        "name": "🎮 Games",
        "icon": "bi-controller",
        "actions": [
            {"type": "app", "app_id": "com.webos.app.hdmi2"},
            {"type": "volume", "level": 25},
        ],
    },
    {
        "id": "musica",
        "name": "🎵 Música",
        "icon": "bi-music-note-beamed",
        "actions": [
            {"type": "app", "app_id": "spotify-beehive"},
            {"type": "volume", "level": 20},
        ],
    },
    {
        "id": "dormir",
        "name": "😴 Dormir",
        "icon": "bi-moon-stars",
        "actions": [
            {"type": "power", "action": "off"},
        ],
    },
]


def load_presets() -> list[dict]:
    """Carrega presets do arquivo ou retorna os padrões."""
    if PRESETS_FILE.exists():
        try:
            return json.loads(PRESETS_FILE.read_text())
        except Exception as e:
            logger.error(f"Erro ao ler presets: {e}")
    return DEFAULT_PRESETS.copy()


def save_presets(presets: list[dict]):
    """Salva presets no arquivo."""
    PRESETS_FILE.write_text(json.dumps(presets, indent=2, ensure_ascii=False))
    logger.info(f"Presets salvos: {len(presets)} itens.")


def get_preset(preset_id: str) -> dict | None:
    """Busca um preset pelo ID."""
    for p in load_presets():
        if p["id"] == preset_id:
            return p
    return None


def add_preset(preset: dict) -> list[dict]:
    """Adiciona um preset."""
    presets = load_presets()
    # Remove existing with same id
    presets = [p for p in presets if p["id"] != preset["id"]]
    presets.append(preset)
    save_presets(presets)
    return presets


def remove_preset(preset_id: str) -> list[dict]:
    """Remove um preset pelo ID."""
    presets = load_presets()
    presets = [p for p in presets if p["id"] != preset_id]
    save_presets(presets)
    return presets
