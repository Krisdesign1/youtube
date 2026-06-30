# Contribuer

Merci de garder les contributions petites, testées et faciles à relire.

## Préparer l'environnement

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

Pour les fonctionnalités média, installe aussi les binaires système:

- `yt-dlp`
- `ffmpeg`

## Lancer les tests

```bash
.venv/bin/python -m pytest
```

## Lancer l'application

```bash
.venv/bin/youtube-script "https://youtu.be/ID_DE_VIDEO"
.venv/bin/youtube-script-gui
```

## Règles de contribution

- Garde les changements liés à un seul objectif.
- Ne commit pas `.venv/`, `build/`, `dist/`, `__pycache__/`, `.pytest_cache/` ou des fichiers téléchargés.
- Ajoute ou adapte les tests quand tu modifies un flux existant.
- Ne stocke jamais de secrets, cookies, tokens ou liens privés dans le dépôt.
- Documente les changements utilisateur dans `README.md` ou `docs/` si le comportement change.

## Pull requests

Avant d'ouvrir une PR:

- Les tests passent localement.
- Le README reste cohérent avec les commandes disponibles.
- Les dépendances nouvelles sont justifiées dans la description.
- Les captures ou logs longs sont résumés au lieu d'être collés intégralement.
