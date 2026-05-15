# Développement

## Installation locale

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

## Commandes utiles

```bash
# Tests
.venv/bin/python -m pytest

# CLI
.venv/bin/python -m youtube_script_app "https://youtu.be/ID_DE_VIDEO"

# GUI
.venv/bin/python -m youtube_script_app.gui

# Build PyInstaller macOS/Linux
./scripts/build_app.sh gui
./scripts/build_app.sh cli
./scripts/build_app.sh both
```

## Build Windows

Depuis PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 gui
```

## Structure du dépôt

```text
.
├── .github/                 # CI, templates issues et pull requests
├── assets/                  # Icônes de l'application
├── docs/                    # Documentation technique
├── scripts/                 # Setup, build et entry points PyInstaller
├── src/youtube_script_app/  # Code applicatif
└── tests/                   # Tests automatisés
```

## Artefacts à ne pas versionner

Les dossiers suivants doivent rester locaux:

- `.venv/`
- `build/`
- `dist/`
- `__pycache__/`
- `.pytest_cache/`

Ils sont déjà couverts par `.gitignore`.
