# Conventions du dépôt

## Git

Tous les travaux vont directement sur `main`. Pas de branche de
fonctionnalité, pas de pull request : on commite sur `main` et on pousse.

```bash
git checkout main
git commit -am "message"
git push -u origin main
```

Cette règle s'applique aussi aux sessions Claude Code : si une branche de
travail dédiée a été créée automatiquement, revenir sur `main` avant de
commiter.

## Projet

Modèle de retraite français en comptes notionnels appliqué rétroactivement.
Voir `README.md` pour l'usage de la CLI `retraite-notionnelle`.

- Code : `src/`
- Données (barèmes, régimes, séries) : `data/`
- Tests : `tests/` — `python -m pytest`
- Seule dépendance hors bibliothèque standard : PyYAML.
