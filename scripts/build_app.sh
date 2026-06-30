#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv}"
PYTHON_BIN="$VENV_DIR/bin/python"
MODE="${1:-gui}"
OS_NAME="$(uname -s)"
SPEC_DIR="$ROOT_DIR/build/spec"
CLI_ENTRYPOINT="$ROOT_DIR/scripts/entrypoints/cli.py"
GUI_ENTRYPOINT="$ROOT_DIR/scripts/entrypoints/gui.py"
PYINSTALLER_COMMON=(--paths "$ROOT_DIR/src")
ICON_PATH="$ROOT_DIR/assets/app.icns"
PYINSTALLER_ICON_ARGS=()
if [[ "$OS_NAME" == "Darwin" && -f "$ICON_PATH" ]]; then
  PYINSTALLER_ICON_ARGS=(--icon "$ICON_PATH")
fi

build_gui() {
  # Exclude unused PIL image plugins to reduce bundle size
  EXCLUDE_PIL=(
    --exclude-module PIL.BmpImagePlugin
    --exclude-module PIL.DdsImagePlugin
    --exclude-module PIL.FitsImagePlugin
    --exclude-module PIL.FliImagePlugin
    --exclude-module PIL.FpxImagePlugin
    --exclude-module PIL.GbrImagePlugin
    --exclude-module PIL.GifImagePlugin
    --exclude-module PIL.Hdf5StubImagePlugin
    --exclude-module PIL.IcnsImagePlugin
    --exclude-module PIL.IcoImagePlugin
    --exclude-module PIL.ImImagePlugin
    --exclude-module PIL.ImtImagePlugin
    --exclude-module PIL.IptcImagePlugin
    --exclude-module PIL.McIdasImagePlugin
    --exclude-module PIL.MicImagePlugin
    --exclude-module PIL.MpoImagePlugin
    --exclude-module PIL.MspImagePlugin
    --exclude-module PIL.PalmImagePlugin
    --exclude-module PIL.PcdImagePlugin
    --exclude-module PIL.PcxImagePlugin
    --exclude-module PIL.PdfImagePlugin
    --exclude-module PIL.PixarImagePlugin
    --exclude-module PIL.PpmImagePlugin
    --exclude-module PIL.PsdImagePlugin
    --exclude-module PIL.QoiImagePlugin
    --exclude-module PIL.SgiImagePlugin
    --exclude-module PIL.SpiderImagePlugin
    --exclude-module PIL.SunImagePlugin
    --exclude-module PIL.TgaImagePlugin
    --exclude-module PIL.TiffImagePlugin
    --exclude-module PIL.WalImageFile
    --exclude-module PIL.XbmImagePlugin
    --exclude-module PIL.XpmImagePlugin
    --exclude-module PIL.XVThumbImagePlugin
    --exclude-module tkinter.test
    --exclude-module unittest
    --exclude-module xmlrpc
    --exclude-module pydoc
  )
  if [[ "$OS_NAME" == "Darwin" ]]; then
    "$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_COMMON[@]}" "${PYINSTALLER_ICON_ARGS[@]}" "${EXCLUDE_PIL[@]}" "$GUI_ENTRYPOINT" --windowed --name youtube-script-gui --specpath "$SPEC_DIR"
  else
    "$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_COMMON[@]}" "${EXCLUDE_PIL[@]}" "$GUI_ENTRYPOINT" --onefile --windowed --name youtube-script-gui --specpath "$SPEC_DIR"
  fi
}

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Environnement virtuel introuvable: $VENV_DIR"
  echo "Exécute d'abord ./scripts/setup_app.sh"
  exit 1
fi

echo "-> Nettoyage des anciens builds"
rm -rf "$ROOT_DIR/build" "$ROOT_DIR/dist"
mkdir -p "$SPEC_DIR"

echo "-> Build PyInstaller ($MODE)"
case "$MODE" in
  gui)
    build_gui
    ;;
  cli)
    "$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_COMMON[@]}" "$CLI_ENTRYPOINT" --onefile --name youtube-script --specpath "$SPEC_DIR"
    ;;
  both)
    "$PYTHON_BIN" -m PyInstaller "${PYINSTALLER_COMMON[@]}" "$CLI_ENTRYPOINT" --onefile --name youtube-script --specpath "$SPEC_DIR"
    build_gui
    ;;
  *)
    echo "Usage: ./scripts/build_app.sh [gui|cli|both]"
    exit 1
    ;;
esac

echo "Build terminé. Fichiers disponibles dans: $ROOT_DIR/dist"
