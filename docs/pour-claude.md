# Consignes pour Claude : travailler avec un fichier kanban-terminal

Ce fichier s'adresse à Claude (Claude Code), dans tout projet dont le fichier d'idées
(`idee.md`, `ideas.md`, `TODO.md`…) est affiché par **kanban-terminal**. L'utilisateur
suit ton travail en direct dans le tableau (`kanban`) et dans son Gantt (touche **G**,
ou `gantt idee.md`). Pour l'activer dans un projet, mets dans son `CLAUDE.md` :

```markdown
@~/Documents/kanban-terminal/docs/pour-claude.md
```

## 1. Ne jamais réécrire le fichier

L'utilisateur l'édite en même temps que toi, et `kanban-tidy` le range à chaque
enregistrement (numérotation du Pending, tags manquants). Donc :

- des **modifications ciblées** seulement, ligne par ligne (outil Edit, ou `sed` sur une
  ligne précise après l'avoir relue) ; jamais un script qui lit tout le fichier puis le
  réécrit, jamais Write sur ce fichier ;
- **relis** la partie à modifier juste avant (le fichier a pu changer) ; si une ligne a
  été changée par l'utilisateur entre-temps, garde sa version ;
- si une version plus ancienne revient (éditeur qui réenregistre), signale-le et refais
  seulement tes propres changements.

## 2. Le format

```markdown
## Règles                       pas de cartes : règles, et réglages du Gantt
- agents: claude, toi           les lignes du Gantt (toi = les relectures de l'utilisateur, ◆)
- unit: 1 min                   la durée d'un créneau
- start: 2026-11-27 11:11       le début de la demande en cours (heure réelle)

## Tags                         un tableau | @tag | description |, une ligne par tag
| @v1 | version 1 (milestone GitHub) |

## Idées                        une section = une catégorie
- [ ] à faire                   [ ] à faire · [_] en cours · [X] fait
- [X] fait (#12) @v1 @bug       (#12) = l'issue GitHub · @tag = filtre / couleur
  - une note                    les lignes indentées sont les notes de la carte
## Correction                   les bugs corrigés
## Plan                         le plan de la demande en cours (voir 4)
## Pending                      la boîte de réception de l'utilisateur
- P1 @tag une demande           numérotées par kanban-tidy (P1, P2…)
```

## 3. Le Pending : la liste des demandes

- « continue with the pending » = traiter les points `- Pn` du Pending.
- Un point peut contenir un log collé (terminal, capture) : c'est la preuve du bug, lis-le.
- Une fois traité, un point **sort du Pending** et devient une ligne `- [X] …` dans
  Idées (ou Correction pour un bug), avec ce qui a été fait, ses issues `(#n)` et ses tags.
- Une question sans code : réponds sous le point avec une ligne `  → …`, et laisse-le
  si l'utilisateur doit encore trancher.
- Un tag nouveau : `kanban-tidy` l'ajoute au tableau « à décrire » ; donne-lui une
  vraie description quand tu sais ce qu'il veut dire.

## 4. Le plan sur le Gantt : à chaque demande

L'utilisateur suit l'avancement en direct sur le Gantt. Au début de chaque demande :

1. Remplace le contenu de « ## Plan » (juste au-dessus de « ## Pending ») : une carte
   par étape, `@claude` pour toi, `@toi` pour ce que l'utilisateur doit relire ou
   essayer (en dernier), chacune avec sa note de créneaux :

   ```markdown
   - [ ] corriger le doublon « su sus » @claude @v1 @bug
     - gantt: 0-3
   - [ ] relire, essayer @toi
     - gantt: 12-15
   ```

2. Mets `- start:` des Règles à l'heure réelle du début (`date "+%Y-%m-%d %H:%M"`).
3. **Pendant le travail** : l'étape en cours passe à `[_]` avec une note `  - at: 40%`,
   puis à `[X]` (enlève la ligne `at:`). La ligne rouge du Gantt avance avec ces
   marqueurs, et seulement avec eux : mets-les à jour au fil de l'eau, pas tout à la fin.
4. **Estimations en minutes réelles** (`unit: 1 min`) : une étape typique (un correctif,
   une petite fonction avec son test) prend 1 à 3 minutes, la doc et le commit environ 2.
   L'en-tête du Gantt affiche « end ≈ HH:MM at this pace (×p) » : si p reste loin de 1,
   corrige les estimations suivantes. (Mesuré : un plan de 130 min a pris 13 min.)

Vérifie avec `gantt idee.md` (une ligne d'en-tête : faits / total, avance ou retard).

## 5. Les issues

Une issue GitHub par changement demandé (`gh issue create`), fermée par le commit
(`Closes #n`), et son numéro dans la ligne `[X]` du fichier. Pour les outils à part
(un autre dépôt), l'issue va dans ce dépôt-là.

## 6. Les commandes

| Commande | Ce qu'elle fait |
|---|---|
| `kanban [fichier]` | le tableau (G : Gantt, U : tests, ? : aide) |
| `gantt fichier [--by task] [--watch]` | le Gantt seul, en une fois ou suivi en direct |
| `kanban-tidy [fichier] [--watch]` | range : Pending numéroté, tags manquants, snippets |
| `kanban-snippets [fichier]` | les tags proposés en tapant `@` dans VS Code |
| `tests [dossier]` | les tests du projet, barre verte / rouge (code 1 si rouge) |
