"""Configuración del usuario: qué perfiles de AWS y qué regiones se recorren."""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "infranettone-ec2-connect"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    # Perfiles de ~/.aws/config que no se recorren (los demás, todos).
    skip_profiles: list[str] = field(default_factory=list)
    # Regiones fijas; vacío = las habilitadas en cada cuenta (describe_regions), más lento pero no se escapa ninguna.
    regions: list[str] = field(default_factory=list)
    # Región para preguntar describe_regions cuando el perfil no tiene una.
    default_region: str = "eu-west-1"
    # Ver también las instancias sin agente de SSM (no se puede conectar, pero se sabe que existen).
    show_unmanaged: bool = False
    # Peticiones a AWS en paralelo (perfil × región).
    workers: int = 16

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n")
