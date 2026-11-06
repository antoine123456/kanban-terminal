# kanban-terminal

Un fichier Markdown d'idées affiché en **tableau Kanban interactif dans le terminal**, assez compact pour le panneau du bas de VS Code.

Le fichier reste la source : chaque action modifie la ligne de la carte (et rien d'autre), et le tableau se recharge tout seul quand le fichier change, par exemple quand tu l'édites dans VS Code en même temps.

```
 À trier 4            │ À faire 11              │ En cours 3                │ Fait 30
▌ui 1. si la carte… @v1│▌faire une page de… #9 @v2│▌integrer un ta… #51✓ #53✓│▌toggle type mode… @v1
▌ui 2. ne jamais p… @v1│▌donner acces aux… #10 @v2│▌à voir dans le … #71✓    │▌timer pour pass… #54✓
Idées › conjugaison  l.24  integrer un tableau de conjugaison avec les radicaux…
```

## Installation

```sh
pipx install -e ~/Documents/kanban-terminal     # la commande « kanban » partout
# ou, sans pipx :
cd ~/Documents/kanban-terminal && python3 -m venv .venv && .venv/bin/pip install -e .
```

## Utilisation

```sh
kanban                 # cherche idee.md, ideas.md, TODO.md… dans le dossier courant
kanban chemin/idees.md
kanban --repo propriétaire/nom   # si le dépôt GitHub n'est pas celui du git du fichier
kanban --theme light             # ou dark ; auto par défaut (aussi : KANBAN_THEME=light)
```

**Clair ou sombre** : comme le terminal autour. Au démarrage, le tableau demande au terminal sa couleur de fond ; sinon il lit le thème de VS Code (`workbench.colorTheme`, ou le thème jour / nuit si `window.autoDetectColorScheme` est activé), sinon l'apparence du système. Il suit ensuite les changements (VS Code ou macOS qui passent en mode nuit) toutes les 3 s. **T** bascule à la main.

Dans VS Code, ouvre un terminal dans le panneau du bas (⌃`), lance `kanban`, puis déplace le terminal où tu veux (clic droit sur l'onglet → « Déplacer dans la zone d'éditeur » pour l'avoir à côté du code).

### Touches

| | |
|---|---|
| ← → ↑ ↓ (ou h j k l), clic | se déplacer ; **Entrée** : détail de la carte (notes, issues) |
| **⇧← ⇧→** (ou `<` `>`), **1 2 3 4** | déplacer la carte : À trier / À faire / En cours / Fait |
| **a** | ajouter une idée dans « À trier » |
| **e** / **E** | modifier le texte / ouvrir le fichier à la ligne dans VS Code (`code -g`) ou `$EDITOR` |
| **o** · **i** · **c** · **g** | GitHub : ouvrir l'issue · créer l'issue de la carte (milestone d'après son tag) · fermer / rouvrir · actualiser |
| **/** · **t** · **s** · **f** · **w** | chercher · filtrer par tag (@v1…) · par section · cacher « Fait » · texte complet sur plusieurs lignes |
| **Échap** · **r** · **T** · **?** · **q** | effacer les filtres · recharger · clair / sombre · aide · quitter |

En sortant une carte de « À trier », le tableau demande dans quelle section la ranger (Idées, Correction…). Une carte passée dans « Fait » qui a une issue encore ouverte propose de la fermer sur GitHub.

## Format du fichier

```markdown
## Idées                          une section = une catégorie de cartes
- [ ] à faire                     [ ] À faire · [_] En cours · [x] ou [X] Fait
- [_] à moitié fait (#12) @v1     #12 = issue GitHub · @v1 = tag (le milestone de l'issue)
  - une note                      les lignes indentées sont les notes de la carte
conjugaison:                      une ligne finie par « : » = groupe des cartes qui suivent
## Correction
- [X] corrigé (#20) @v1
## Pending                        la boîte de réception (Pending, Inbox, À trier) : chaque « - » est une carte
- [ui] une idée à classer         une marque inconnue devient un tag ([ui] → @ui une fois rangée)
- une autre
```

Une section « Règles » (ou « Rules ») est ignorée.

Les issues GitHub passent par la commande `gh`, si elle est installée et connectée. Sans elle, le tableau marche quand même et affiche juste les numéros.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests
```
