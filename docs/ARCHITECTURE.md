# Architecture

Ce projet est une application Python desktop et CLI pour extraire des transcriptions YouTube et générer des médias avec `yt-dlp` et `ffmpeg`.

## Vue d'ensemble

```text
Utilisateur
  ├─ CLI: youtube-script
  │   └─ youtube_script_app.cli
  └─ GUI: youtube-script-gui
      └─ youtube_script_app.gui.TranscriptApp

Transcription
  ├─ core.transcript_fetcher
  ├─ core.transcript_formatter
  └─ core.moment_analyzer

Média
  ├─ downloads.utils
  ├─ downloads.history
  ├─ video.renderer
  └─ core.subtitle_renderer
```

## Points d'entrée

- `python -m youtube_script_app`: lance la CLI via `youtube_script_app.__main__`.
- `youtube-script`: entry point console défini dans `pyproject.toml`.
- `youtube-script-gui`: entry point GUI défini dans `pyproject.toml`.
- `scripts/entrypoints/`: points d'entrée utilisés par PyInstaller.

## Modules principaux

### `core.transcript_fetcher`

Responsable de:

- Extraire l'identifiant vidéo YouTube.
- Appeler `youtube-transcript-api`.
- Normaliser les erreurs réseau, les sous-titres absents et les langues indisponibles.
- Retourner un `TranscriptResult` avec texte formaté, transcription brute et métadonnées.

### `core.transcript_formatter`

Convertit les blocs de transcription en:

- Texte brut.
- Texte avec timestamps.
- JSON.

### `core.moment_analyzer`

Classe les minutes de transcription avec une heuristique:

- Mots clés forts, moyens et faibles.
- Ponctuation expressive.
- Questions, transitions, rires, nombres.
- Normalisation par densité de mots.

Le résultat est une liste de `MomentScore`.

### `gui.TranscriptApp`

Orchestre l'interface Tkinter:

- Validation des champs.
- Génération de transcription dans un thread.
- Affichage des résultats et cartes de moments forts.
- File de téléchargement.
- Suivi de progression `yt-dlp`.
- Prévisualisation et variantes vidéo.
- Persistance des préférences et de l'historique.

### `downloads.utils`

Contient les helpers purs pour:

- Construire les commandes `yt-dlp`.
- Parser les tailles de téléchargement.
- Nommer les variantes de fichiers.
- Normaliser les ratios de taille/position du logo et les opacités.

### `video.renderer`

Construit et lance les commandes `ffmpeg` pour:

- Convertir en 9:16.
- Ajouter un logo dimensionné et positionné par ratios de la résolution cible.
- Ajouter des sous-titres ASS.
- Appliquer un effet vidéo.
- Générer une prévisualisation basse résolution.

### `core.subtitle_renderer`

Produit les documents ASS utilisés par `ffmpeg`:

- Styles de sous-titres.
- Découpe des sous-titres à la fenêtre du clip.
- Échappement des chemins et textes.

## Persistance locale

Les fichiers utilisateur sont stockés hors dépôt:

- Logs: `~/.youtube-script/app.log`
- Préférences GUI: `~/.youtube-script/gui_settings.json`
- Historique téléchargements: `~/.youtube-script/download_history.json`

## Dépendances externes

- `youtube-transcript-api`: récupération des transcriptions YouTube.
- `yt-dlp`: téléchargement vidéo/audio et découpage de sections.
- `ffmpeg`: MP3, clips, effets, logo et sous-titres incrustés.

`yt-dlp` et `ffmpeg` sont des dépendances runtime optionnelles pour les fonctionnalités média. La transcription seule n'en dépend pas.
