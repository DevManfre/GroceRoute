---
name: merge-main
description: Use when merging a branch into main ("mergia", "merge su main", "chiudi il branch"), or cleaning up branches after a merge.
---

# Merge su main e pulizia dei branch

Si esegue su richiesta dell'utente: la richiesta vale per **tutta** la sequenza qui sotto, push e cancellazione del branch incluse. Restano bloccanti (fermarsi e riferire): CI rossa, conflitti, working tree sporco, test rossi. Commit e messaggi: skill `git-commit-style` (gitmoji, inglese, nessun co-autore, nemmeno nella PR).

## 1. Controlli prima del merge (fermarsi se uno fallisce)
- `git status --porcelain` vuoto: niente file non committati che andrebbero persi o trascinati.
- Branch corrente ≠ `main`; annota il nome in `B`.
- Test verdi sul branch (`pytest`, quando esisteranno). Ogni controllo legge l'exit code reale: `; echo "exit $?"`, mai in pipe con `tail`/`grep`.
- Ultimo commit pushato (`git push -u origin "$B"`). Se il repo ha GitHub Actions, CI verde su quel commit:
  `gh run watch $(gh run list --branch "$B" -L 1 --json databaseId -q ".[0].databaseId") --exit-status`.
  Se non ci sono workflow, dirlo nel resoconto e proseguire.

## 2. Merge via Pull Request
Il merge verso `main` (default branch) passa **sempre** da una PR mergiata su GitHub: i commit del branch compaiono sul grafico dei contributi del profilo (email autore verificata + arrivo sul default branch). Un `git merge` locale seguito da push spesso non li fa contare.

```bash
git fetch origin
git push origin "$B:$B"          # solo se ci sono commit non pushati; nome esplicito
gh pr create --base main --head "$B" --title "🔀 <TITLE> - merge $B into main" --body "<descrizione>"
gh pr view <n> --json mergeable,mergeStateStatus   # CONFLICTING/DIRTY: fermarsi
gh pr checks <n> --watch --fail-fast               # se ci sono check: verdi prima del merge
gh pr merge <n> --merge --subject "🔀 <TITLE> - merge $B into main" --body ""
```
`--subject` è obbligatorio: senza, GitHub usa "Merge pull request #n from …" e il commit di merge esce dal formato `git-commit-style`.
`<TITLE>` = l'area toccata (`SOURCES`, `OPTIMIZER`, `MATCHER`, `BOT`, `DB`, `README`…). Titolo e corpo PR in inglese, formato `git-commit-style`, senza righe "Generated with" o co-autori.
- **Vietato `--squash` e `--rebase`** su `main`: fondono o riscrivono i commit e sul grafico non resterebbe traccia degli originali. Vietato anche `git merge <branch>` locale verso `main`. Se il repo non permette il merge commit (`allow_merge_commit`), fermarsi e riferire.
- **Conflitti**: **non** risolverli a intuito: riporta i file in conflitto all'utente e chiedi.
- Merge verso branch **diversi da `main`** (es. aggiornare un branch da `main`): `git merge` locale.
- Non riscrivere la storia già pushata (`--force`, `rebase`, `commit --amend` su commit pushati) e non cambiare l'email autore a metà lavoro: un'email non associata all'account GitHub fa sparire i commit dal grafico.

## 3. Aggiornamento locale e pulizia
La PR ha già portato `main` su origin: **niente `git push origin main`**.
```bash
git switch main && git pull --ff-only origin main
git merge-base --is-ancestor "$B" origin/main               # deve uscire 0
git branch -d "$B"                                          # -d, mai -D: rifiuta se non è mergiato
git ls-remote --exit-code --heads origin "$B" && git push origin --delete "$B"
git fetch --prune
```
Se `git pull --ff-only` fallisce o `-d` rifiuta, **non** usare `--force`, `-D` né reset: fermati e riferisci all'utente.

## 4. Verifica e resoconto
`git log --oneline --graph -5`, `git branch -a`: il branch non esiste più né in locale né in remoto. Riporta lo SHA del merge e l'esito della CI. Se il branch chiudeva una voce della Roadmap del README, ricorda che si può spuntare.
