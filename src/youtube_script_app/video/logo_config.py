"""Logo validation and metadata helpers for video rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE_MB = 20
LOGO_SIZE_MODES = {"relative", "original"}
MAX_LOGO_PIXELS = 80_000_000


@dataclass
class LogoConfig:
    """Validated logo configuration built before preview or rendering."""

    path: Path
    position: str
    size_mode: str
    slider_value: float
    opacity: float
    x_ratio_custom: float = 0.95
    y_ratio_custom: float = 0.05

    original_width: int = field(init=False)
    original_height: int = field(init=False)
    has_transparency: bool = field(init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.size_mode = str(self.size_mode or "relative").strip().lower()
        self.position = str(self.position or "top-right").strip().lower().replace("_", "-")
        self.slider_value = float(self.slider_value)
        self.opacity = float(self.opacity)
        self.x_ratio_custom = float(self.x_ratio_custom)
        self.y_ratio_custom = float(self.y_ratio_custom)
        self._validate()

    def _validate(self) -> None:
        if not str(self.path).strip():
            raise FileNotFoundError("Aucun fichier logo sélectionné.")
        if not self.path.exists():
            raise FileNotFoundError(f"Fichier logo introuvable : {self.path}")
        if not self.path.is_file():
            raise ValueError(f"Le chemin logo n'est pas un fichier : {self.path}")

        suffix = self.path.suffix.lower()
        if suffix not in SUPPORTED_FORMATS:
            accepted = ", ".join(sorted(SUPPORTED_FORMATS))
            raise ValueError(
                f"Format non supporté : '{suffix}'. Formats acceptés : {accepted}"
            )

        size_mb = self.path.stat().st_size / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"Fichier logo trop lourd : {size_mb:.1f} MB "
                f"(maximum : {MAX_FILE_SIZE_MB} MB)"
            )

        try:
            with Image.open(self.path) as img:
                width, height = img.size
                pixels = width * height
                if pixels > MAX_LOGO_PIXELS:
                    raise ValueError(
                        f"Image logo trop grande : {width}x{height}px "
                        f"({pixels:,} pixels). Maximum autorisé : "
                        f"{MAX_LOGO_PIXELS:,} pixels."
                    )
                img.verify()
        except Image.DecompressionBombError as error:
            raise ValueError(
                "Image logo trop grande pour être chargée en sécurité. "
                "Redimensionne le fichier avant de l'utiliser comme logo "
                "(par exemple 2000 px de large ou moins)."
            ) from error
        except Exception as error:
            raise ValueError(f"Fichier image corrompu : {error}") from error
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(f"Fichier image corrompu : {error}") from error

        try:
            with Image.open(self.path) as img:
                self.original_width, self.original_height = img.size
                self.has_transparency = img.mode in {"RGBA", "LA", "P"}
        except Image.DecompressionBombError as error:
            raise ValueError(
                "Image logo trop grande pour être chargée en sécurité. "
                "Redimensionne le fichier avant de l'utiliser comme logo "
                "(par exemple 2000 px de large ou moins)."
            ) from error

        if self.original_width < 20 or self.original_height < 20:
            raise ValueError(
                f"Logo trop petit : {self.original_width}x{self.original_height}px "
                "(minimum 20x20)"
            )
        if self.size_mode not in LOGO_SIZE_MODES:
            raise ValueError(
                f"Mode de taille logo inconnu : '{self.size_mode}'. "
                "Valeurs acceptées : 'relative', 'original'."
            )
        if not 20 <= self.slider_value <= 80:
            raise ValueError(
                f"slider_value hors plage : {self.slider_value} (attendu : 20-80)"
            )
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError(
                f"opacity hors plage : {self.opacity} (attendu : 0.0-1.0)"
            )

    @property
    def aspect_ratio(self) -> float:
        return self.original_height / self.original_width

    @classmethod
    def from_gui_state(cls, state: dict) -> "LogoConfig":
        def first_present(*keys: str, default: object) -> object:
            for key in keys:
                if key in state and state[key] is not None:
                    return state[key]
            return default

        return cls(
            path=Path(str(first_present("logo_path", "download_logo_path", default=""))),
            position=str(
                first_present("logo_position", "download_logo_position", default="top-right")
            ),
            size_mode=str(
                first_present("logo_size_mode", "download_logo_size_mode", default="relative")
            ),
            slider_value=float(
                first_present("logo_size", "download_logo_scale_percent", default=30)
            ),
            opacity=(
                float(
                    first_present(
                        "logo_opacity",
                        "download_logo_opacity_percent",
                        default=100,
                    )
                )
                / 100.0
            ),
            x_ratio_custom=float(state.get("download_logo_x_ratio", 0.95)),
            y_ratio_custom=float(state.get("download_logo_y_ratio", 0.05)),
        )

    def to_settings_dict(self) -> dict:
        return {
            "download_logo_path": str(self.path),
            "download_logo_position": self.position,
            "download_logo_size_mode": self.size_mode,
            "download_logo_scale_percent": int(round(self.slider_value)),
            "download_logo_opacity_percent": int(round(self.opacity * 100)),
            "download_logo_x_ratio": self.x_ratio_custom,
            "download_logo_y_ratio": self.y_ratio_custom,
        }
