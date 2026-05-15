# Générateur de script YouTube et téléchargeur vidéo

Outil pour récupérer la transcription d'une vidéo YouTube et la présenter sous forme de script. L'interface graphique permet aussi de télécharger une vidéo complète ou son audio depuis tout lien supporté par `yt-dlp`.

- **CLI** via le package `youtube_script_app`
- **Interface graphique** via `youtube_script_app.gui`
- **Binaire autonome** ou alias shell

## Statut du projet

- Version actuelle : `0.1.0`
- Langage : Python 3.10+
- Interface : CLI + Tkinter
- Tests : `pytest`
- Build desktop : PyInstaller

## Documentation projet

- [Architecture](docs/ARCHITECTURE.md)
- [Développement](docs/DEVELOPMENT.md)
- [Checklist GitHub](docs/GITHUB_RELEASE_CHECKLIST.md)
- [Contribution](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Sécurité](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Pré-requis

- Python 3.10+
- Connexion Internet permettant d'accéder aux liens à traiter
- Dépendance : `pip install youtube-transcript-api`
- (Optionnel pour la GUI) `pip install tk` sous certaines distributions Linux
- (Optionnel pour télécharger vidéo/audio depuis YouTube, TikTok, Instagram, X, etc.) :
  - `yt-dlp`
  - `ffmpeg` pour extraire l'audio MP3 et découper/convertir les extraits

## Setup rapide (appli "normale")

Depuis le dossier du projet :

```bash
chmod +x scripts/setup_app.sh scripts/build_app.sh
./scripts/setup_app.sh
```

Ensuite :

- Lancer la GUI : `.venv/bin/youtube-script-gui`
- Lancer la CLI : `.venv/bin/youtube-script "https://youtu.be/ID_DE_VIDEO"`

Pour générer un exécutable :

```bash
./scripts/build_app.sh gui   # ou cli / both
```

Le résultat est créé dans `dist/`.

Sous Windows, ouvre PowerShell depuis le dossier du projet :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 gui
```

Le `.exe` Windows est généré dans `dist\windows\`.

## Ligne de commande

```bash
python -m youtube_script_app "https://youtu.be/ID_DE_VIDEO" -l fr -f text-timestamps -o script.txt
```

- `-l` / `--language` : répéter l'option pour chaque langue souhaitée (`fr`, `en`, etc.).
- `-f` / `--format` : `text`, `text-timestamps`, ou `json`.
- `--most-viewed` : ajoute une liste des moments forts estimés. Ex: `--most-viewed 5`.
- `--csv` : export CSV des moments forts estimés.
- `-t` / `--timestamps` : rétrocompatibilité pour `text-timestamps`.
- `-o` / `--output` : enregistre dans un fichier (sinon affichage terminal).

Avec `--most-viewed` + `--format json`, la sortie devient un objet JSON contenant `most_viewed` et `transcript`.

Sans URL, le script te la demandera au lancement :

```bash
python -m youtube_script_app
```

## Interface graphique

```bash
python -m youtube_script_app.gui
```

1. Coller un lien. La transcription reste limitée à YouTube ; les téléchargements vidéo/audio acceptent les liens supportés par `yt-dlp`.
2. (Facultatif) Entrer les codes langue séparés par des virgules (`fr,en`).
3. Choisir le format de sortie (texte, horodatages ou JSON).
4. (Optionnel) Activer **Moments forts estimés** et choisir le nombre.
5. (Optionnel) Choisir **Format vidéo** (mp4/webm) et **Durée extrait** pour le téléchargement des clips.
   - Choisir **Format final** : `Normal 16:9` (horizontal) ou `Short 9:16` (vertical).
   - Les options de téléchargement (16:9/9:16, format, durée, logo, position, taille, opacité) sont mémorisées automatiquement pour les prochains lancements.
   - Cocher/Décocher **Intégrer le logo** pour l’activer ou non sur les clips et la vidéo entière.
   - Choisir un **Logo à intégrer** (PNG/JPG/WebP), puis sa **Position** (`Haut`, `Milieu`, `Bas`).
   - Choisir **Mode taille logo** : `Taille originale` conserve les dimensions du fichier logo ; `Personnalisée` active le curseur.
   - Ajuster **Taille logo** (curseur de 20% à 80% de la taille originale du logo en mode personnalisé) pour régler sa visibilité sans modifier le code.
   - Ajuster **Opacité logo** (curseur de 10% à 100%) pour le rendre discret ou très visible.
   - Cocher **Ajouter sous-titres** pour incruster les sous-titres dans les clips générés à partir de la transcription récupérée.
   - Choisir un **Design sous-titres** : `Impact TikTok`, `Moderne blanc`, `Cinéma`, `Boîte noire` ou `Minimal`.
   - Choisir un **Effet vidéo** : `Aucun`, `Noir et blanc`, `Contraste fort`, `Cinéma sombre` ou `Vintage`.
   - Choisir un **Preset créatif** pour appliquer rapidement un ensemble cohérent de réglages (`TikTok Viral`, `Podcast Clip`, `Cinéma N&B`, `Documentaire`, `Gaming Punch`).
6. Cliquer sur **Générer la transcription YouTube** : une barre de progression et l’état indiquent l’avancement.
7. Depuis la zone de transcription :
   - **Copier le texte** pour l’envoyer dans le presse-papiers.
   - **Réinitialiser** pour recommencer.
   - **Enregistrer…** pour sauvegarder dans un fichier texte.
   - **Exporter liste** pour sauvegarder les moments détectés (CSV, TXT ou JSON).
   - **Télécharger extraits** pour récupérer les clips correspondants (file d’attente + progression globale 0% → 100%).
   - **Télécharger la vidéo entière** pour récupérer la vidéo complète depuis le lien courant.
   - **Télécharger l’audio (MP3)** pour extraire uniquement la piste audio.
   - Bouton **📋** sur chaque extrait pour copier son texte (fenêtre temporelle du clip) dans le presse-papiers.
   - Bouton **Aperçu** sur chaque extrait pour générer quelques secondes temporaires en basse résolution avec le design, l’effet, le format 9:16 et le logo sélectionnés avant de lancer le téléchargement final.
   - Bouton **Télécharger** sur chaque moment pour récupérer un seul clip.
   - Les fichiers téléchargés utilisent automatiquement le texte de l’extrait comme base de nom.
   - **Annuler** pour ignorer une récupération en cours.
   - **Coller l'URL** et **Ouvrir le lien** sont disponibles sous le champ URL.

Les sous-titres stylisés et les effets vidéo sont générés localement avec `ffmpeg`. Ils ne nécessitent aucun service payant. Les sous-titres utilisent les horodatages fournis par YouTube ; ils sont donc synchronisés par phrase ou bloc de transcription, pas mot par mot.

Raccourcis utiles :

- `Ctrl+Enter` : lancer la génération.
- `Ctrl+V` : coller dans le champ actif (URL/langues).
- `Ctrl+Home` : aller en haut de l’application.
- `Ctrl+End` : aller en bas de l’application.
- `Alt+↑` / `Alt+↓` : défiler d’une page.

Navigation :

- Une barre de défilement verticale permet de parcourir toute l’interface.
- Les boutons `↑ Haut` et `↓ Bas` dans l’en-tête permettent d’aller rapidement au début/à la fin.

Astuce : l’interface affiche le format choisi, la langue utilisée (si disponible), un compteur lignes/caractères et une zone dédiée aux moments forts estimés.

## Créer un exécutable avec PyInstaller

PyInstaller produit un binaire pour le système qui lance le build. Pour créer un `.exe`, lance le build sur Windows.

1. Préparer l'environnement :
   ```bash
   ./scripts/setup_app.sh
   ```
2. Construire l'exécutable :
   ```bash
   ./scripts/build_app.sh gui
   ```
   - CLI seulement : `./scripts/build_app.sh cli`
   - Les deux : `./scripts/build_app.sh both`
3. Les fichiers de sortie se trouvent dans `dist/`.
   - macOS (GUI) : bundle `.app` prêt au double-clic.
   - Windows/Linux (GUI) : binaire GUI.

### Build Windows

Depuis PowerShell sur Windows :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 gui
```

Options disponibles :

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 cli
powershell -ExecutionPolicy Bypass -File .\scripts\build_app_windows.ps1 both
```

Sorties :

- GUI : `dist\windows\youtube-script-gui.exe`
- CLI : `dist\windows\youtube-script.exe`

Astuce : ajoute `--icon chemin/icône.ico` si tu disposes d'une icône personnalisée.

## Alias shell pratique

Dans `~/.zshrc` (ou `~/.bashrc` selon ta configuration), ajoute par exemple :

```bash
alias youtube-script='cd /Users/user/Downloads/youtube && python3 -m youtube_script_app'
alias youtube-script-gui='cd /Users/user/Downloads/youtube && python3 -m youtube_script_app.gui'
```

Recharge ensuite ta configuration (`source ~/.zshrc`) ou ouvre un nouveau terminal. Tu pourras alors lancer directement `youtube-script` ou `youtube-script-gui`.

## Problèmes courants

- **"Unable to reach YouTube…"** : vérifie ta connexion ou tout filtrage réseau/DNS.
- **"No transcript found…"** : la vidéo n'a pas de sous-titres pour les langues demandées.
- **Interface Tkinter absente** : installe `python3-tk` si nécessaire (Linux).
- **Téléchargement vidéo/audio impossible** : installe `yt-dlp` et `ffmpeg`, puis vérifie que le lien est supporté par `yt-dlp`.

## Logs

Un fichier log est écrit dans `~/.youtube-script/app.log` pour aider au diagnostic.

## Structure du projet

- `.github/` : workflows CI, templates d'issues et pull requests.
- `docs/` : documentation technique et développement.
- `src/youtube_script_app/` : package applicatif.
- `src/youtube_script_app/core/` : transcription, formatage et analyse des moments forts.
- `src/youtube_script_app/downloads/` : commandes de téléchargement, variantes vidéo et historique.
- `assets/` : icône et ressources graphiques de l’application.
- `scripts/` : scripts d'installation, de build et points d'entrée PyInstaller.
- `tests/` : tests automatisés.

Les artefacts locaux `.venv/`, `build/`, `dist/`, `__pycache__/` et `.pytest_cache/` ne doivent pas être versionnés.

## Tests

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Le workflow GitHub Actions exécute aussi les tests sur Python 3.10, 3.11 et 3.12.

Bon script !
