#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "-> Création de l'environnement virtuel: $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"

echo "-> Mise à jour de pip"
"$VENV_DIR/bin/python" -m pip install --upgrade pip

echo "-> Installation de l'application (mode standard + build)"
"$VENV_DIR/bin/python" -m pip install ".[build]"

echo
echo "Setup terminé."
echo "Lancer la GUI : $VENV_DIR/bin/youtube-script-gui"
echo "Lancer la CLI : $VENV_DIR/bin/youtube-script"
echo
echo "Optionnel pour les clips: installer les binaires systeme 'yt-dlp' et 'ffmpeg'."
