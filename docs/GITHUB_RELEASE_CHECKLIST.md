# Checklist GitHub

Avant de publier le dépôt:

- Initialiser Git si ce n'est pas encore fait: `git init`.
- Choisir explicitement une licence et ajouter un fichier `LICENSE`.
- Vérifier que `.venv/`, `build/`, `dist/`, `.pytest_cache/`, `__pycache__/` et `.DS_Store` ne sont pas suivis.
- Lancer `.venv/bin/python -m pytest`.
- Créer le dépôt GitHub et pousser la branche principale.
- Vérifier que GitHub Actions passe sur Python 3.10, 3.11 et 3.12.
- Activer les alertes de sécurité GitHub si le dépôt est public.
- Créer une release seulement à partir d'un état testé.

Commandes utiles:

```bash
git init
git add .
git status
.venv/bin/python -m pytest
git commit -m "Prepare project for GitHub"
```
