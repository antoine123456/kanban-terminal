# kanban-terminal

Un fichier Markdown d'idées affiché en **tableau Kanban interactif dans le terminal**, assez compact pour le panneau du bas de VS Code.

Le fichier reste la source : chaque action modifie la ligne de la carte (et rien d'autre), et le tableau se recharge tout seul quand le fichier change, par exemple quand tu l'édites dans VS Code en même temps.

![Le tableau Kanban dans un terminal](docs/board.png)

## Installation

Il faut Python 3.10 ou plus.

```sh
git clone https://github.com/antoine123456/kanban-terminal.git
pipx install -e kanban-terminal          # les commandes kanban, gantt et tests partout
# ou, sans pipx :
cd kanban-terminal && python3 -m venv .venv && .venv/bin/pip install -e .
```

Pour les issues GitHub (touches **o i c g**), installer aussi [`gh`](https://cli.github.com) et lancer `gh auth login` une fois.

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
| **x** · **X** | Claude Code : traiter la carte choisie · traiter toute la boîte « À trier » (voir plus bas) |
| **Échap** · **r** · **T** · **?** · **q** | effacer les filtres · recharger · clair / sombre · aide · quitter |

En sortant une carte de « À trier », le tableau demande dans quelle section la ranger (Idées, Correction…). Une carte passée dans « Fait » qui a une issue encore ouverte propose de la fermer sur GitHub.

### Lancer Claude depuis le tableau

**x** lance [Claude Code](https://claude.com/claude-code) sur la carte choisie : le tableau s'efface, `claude` s'ouvre dans le même terminal, dans le dossier du fichier, avec le texte de la carte (et ses notes) comme première demande. **X** lui demande de traiter toute la boîte « À trier » (« exécute Pending »). Quand tu quittes Claude (`/exit` ou ⌃D deux fois), le tableau revient, rechargé avec ce que Claude a changé dans le fichier. Autre commande : `KANBAN_CLAUDE="claude --model opus" kanban`.

### Vue Gantt (G)

**G** passe du tableau au Gantt du même fichier (par agent, puis par tâche, puis retour au tableau). Aussi en ligne de commande : `gantt fichier.md` (`--by task`, `--play` rejoue le plan, `--watch` reste ouvert et suit le fichier).

Une carte apparaît sur le Gantt si elle a une note `gantt: début-fin` (en créneaux). Son tag `@volet1`… donne la couleur, son tag d'agent donne la ligne. Dans la section Règles :

```markdown
- agents: lead, scan, you          l'ordre des lignes (you = tes relectures, ◆)
- unit: 5 min                      la durée d'un créneau
- start: 2026-11-18 15:00          optionnel : le début réel du travail
```

Les barres n'ont pas de texte : trois teintes de la couleur de la phase, █ fait, ▒ en cours, ░ à faire.

La **ligne rouge ┃** montre l'avancement, et seuls des **marqueurs** la font bouger : une carte cochée `[_]` ou `[X]`, ou une note `at: 60%` sous une carte en cours (la barre se remplit jusque-là). Elle se place sur la première carte pas finie, à son début ou à son marqueur : tout ce qui est à gauche est fait. Avec `start:` dans Règles, une ligne grise **┊** montre l'horloge, et l'en-tête dit l'avance ou le retard.

### Vue Tests (U)

**U** affiche les tests du projet comme l'ancien lanceur JUnit : une barre **verte** si tout passe, **rouge** dès qu'un test échoue, puis `Runs · Errors · Failures · Skipped`. En dessous, les échecs d'abord, puis les autres en gris. ↑↓ sur un test montre sa trace, **r** relance. En ligne de commande : `tests [dossier]`, qui renvoie le code 1 si c'est rouge.

Les résultats sont lus dans des rapports **JUnit XML**, le format que savent écrire tous les outils de test. Le projet est trouvé en remontant à la racine git, puis :

| Projet | Commande lancée |
|---|---|
| `pom.xml` | `mvn test` → `target/surefire-reports/` |
| `build.gradle(.kts)` | `gradle test` → `build/test-results/test/` |
| Python avec pytest | `pytest --junitxml` |
| Python avec `tests/` | unittest, via `unittest_xml.py` (unittest n'écrit pas de JUnit XML) |
| autre (Jest, cargo…) | `tests --cmd "…" --report "chemin/*.xml"` |

Python : le `.venv` du projet est utilisé s'il existe.

## Format du fichier

```markdown
## Idées                          une section = une catégorie de cartes
- [ ] à faire                     [ ] À faire · [_] En cours · [x] ou [X] Fait
- [_] à moitié fait (#12) @v1     #12 = issue GitHub · @v1 = tag (le milestone de l'issue)
- [ ] mise de côté @v1 @plus-tard @plus-tard l'emporte : carte grisée, hors du filtre @v1
  - une note                      les lignes indentées sont les notes de la carte
conjugaison:                      une ligne finie par « : » = groupe des cartes qui suivent
## Correction
- [X] corrigé (#20) @v1
## Pending                        la boîte de réception (Pending, Inbox, À trier) : chaque « - » est une carte
- [ui] une idée à classer         une marque inconnue devient un tag ([ui] → @ui une fois rangée)
- une autre
```

Une section « Règles » (ou « Rules ») n'a pas de cartes. Elle peut décrire les tags, une ligne par tag :

```markdown
## Règles
- @idée: une idée pas encore planifiée
- @volet1: préparer
```

**Couleurs des tags** : un jalon (`@v1`, `@volet2`…) colore la barre à gauche de la carte, avec la même couleur que sa phase dans le Gantt. Les autres tags s'écrivent avant le texte, en gras et en couleur (toujours la même pour un tag) : `[idée]` dans la boîte « À trier » et `@idée` une fois la carte rangée s'affichent pareil. Le menu **t** et le détail (**Entrée**) montrent la description de chaque tag. Un jalon sans description prend le nom de la section où sont ses cartes.

Les issues GitHub passent par la commande `gh`, si elle est installée et connectée. Sans elle, le tableau marche quand même et affiche juste les numéros.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests
```
