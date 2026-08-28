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

- Modèle de référence, en Python : `src/`
- Données (barèmes, régimes, séries) : `data/`
- Ce que le site charge : `moteur/` — portage JavaScript du modèle (`moteur/js/`),
  paquet de données et feuille de style, tous deux produits par
  `python scripts/construire_donnees.py`. À reconstruire après toute modification
  des données ou du style.
- Tests : `tests/` — `python -m pytest` (lance aussi `node --test`)
- Seule dépendance hors bibliothèque standard : PyYAML. Le portage JavaScript
  n'utilise aucune bibliothèque.

Le Python de `src/` fait foi. Toute modification du modèle doit être portée dans
`moteur/js/`, puis les témoins régénérés par
`python scripts/construire_temoins.py` : leur diff montre, chiffre par chiffre,
ce que le changement déplace.
