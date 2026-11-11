# Fonti storiche e lacune

[Indice](README.md) · [Progetto](../../README.md)

## Metodo e baseline

Ispezionati stato Git, tutti i 17 commit locali, diff/stat, sorgenti applicativi, test e quattro migrazioni fino a `2d75ebd`. Stato iniziale pulito su main allineato al riferimento locale origin/main. Nessuna modifica applicativa o migrazione eseguita sul DB locale per questa riorganizzazione.

Fonti primarie: Git (`git log --reverse`, `git show <hash>:<percorso>`, diff per commit), README backend e specifica Execution Planning. Le schede elencano i percorsi di implementazione e test modificati da ciascun commit. Per leggere tutto il delta usare `git show <hash>`.

## Registro commit

```text
b2712331cb216a887b686391e15bc8cda29f1885 chore: initialize JACK backend with FastAPI and tests
fc5d64d9319d0cf5f2d8646a5a0fa316fd481517 feat: add task models and state machine
09f5dea4b8c51f8b393593c36f0f1eaada0f0f6f feat: implement in-memory task manager
e8b69a65d965c5c882f9a1b6e252a3e22629a16c feat: expose task management REST API
6577f0a35b20150ff577945301cea6d0b010def8 feat: add task status update endpoint
b2473813bbff0f3b631bef3f9188a486e7e47103 feat: add persistent task storage with SQLAlchemy and Alembic
96c832d4deeb5c2b7496befa66528c265991eb0a feat: add task execution engine and operation registry
26c3efcb8c7f80e011df48849fdc8d9deee9abad feat(tasks): harden execution, recovery and atomic transitions
0fad361254374b75364ee4a186d141222ebeda3a feat(agents): introduce agent contract and registry
896fb8e55f6e0663c97266768d580a7cbb679158 feat(agents): implement sequential agent orchestration
3924e09dd8757916e6029caf5c20b463d0ae0c20 feat(research): introduce business research agent
c08b2482580de040dc10770d9f457518ca3fabdc feat(research): add live research providers
325b1ec051f45219e527894b18c9b32701ec141d feat(research): add commercial market intelligence
66d1b9324ed07836fa7732ac6a61913f9f6ac84c feat(validation): add business validation agent
f1908e63a93d61e45ae7e548b007cf27ce48e231 feat(portfolio): add persistent venture management
6bbf4b39181538421d2274bca39e7f63aa75605d feat(portfolio): complete evidence-based advisory decision engine
2d75ebd4258e64b5da888bf85d54de53da372104 feat(planning): add evidence-gated MVP execution plans and human review

```

## Persistenza verificabile

| Revisione | Precedente | Aggiunte |
| --- | --- | --- |
| 9037f069938f | base | tasks |
| 097_portfolio | 9037f069938f | ventures, portfolio_events |
| 098_decisions | 097_portfolio | portfolio_decisions |
| 101_planning | 098_decisions | execution_plans |

Le revisioni sono in [versions](../../backend/alembic/versions). Gli upgrade/downgrade nei test portfolio/decisioni/planner usano DB temporanei; i downgrade eliminano le rispettive tabelle, non costituiscono backup.

## Fonte conversazionale e futuro

[Avvio di Jarvis](chatgpt-conversation://6ab7a864-5130-83eb-a909-d264e93396c6), messaggio `562c2880-681d-450f-bac0-c53a415eadc7`: proposta delle voci 10.2–10.6, 11.1–11.6, 12.1–12.6, 13–15 e requisiti trasversali. Questa e fonte di intenzioni, non prova di implementazione. I dettagli di progettazione nelle schede future sono proposte di questa riorganizzazione.

## Lacune esplicite

- Nessuna numerazione 01–08 esplicita nei commit o nel README originario (inizialmente vuoto): otto fasi ricostruite, nessuna attribuzione numerica individuale.
- Nessun registro ADR separato: autori delle scelte, discussioni, alternative formalmente scartate e motivazioni non espresse sono non documentati.
- La chat dichiara 239 test alla 09.8 e 255 alla 10.1: non sono report CI versionati; non vengono spacciati per verifiche ripetute su ciascuno snapshot.
- `research-live-crossref.json` e citato nel README storico ma non e tracciato nel repository; il risultato live resta una dichiarazione documentata, non una verifica ripetuta qui. Non sono stati contattati provider reali.
- Git dimostra il codice committato, non lo stato di tutti gli esperimenti locali o l'istante di pubblicazione remoto. I risultati attuali sono in [VERIFICATION.md](VERIFICATION.md).
- Pianificazione futura: nessuna data, budget approvato, API o schema definitivo ricostruibile. La presenza di un titolo non equivale a una decisione presa.

## Conservazione contenuti

Il README root non esisteva. Il precedente README backend era dedicato a 09.1–09.8: i corpi delle sezioni sono conservati nelle rispettive pagine, inclusi esempi, configurazioni e istruzioni. I collegamenti operativi sono nel nuovo README backend. `backend/EXECUTION_PLANNING.md` e mantenuto integralmente; la pagina 10.1 ne conserva il contenuto tecnico. La nota sull'artefatto live non tracciato rende esplicita una lacuna senza inventare il file.
