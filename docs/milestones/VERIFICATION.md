# Verifiche della riorganizzazione

[Indice](README.md) · [Progetto](../../README.md)

Data: 11 novembre 2026 (Europe/Rome). Baseline applicativa: `2d75ebd4258e64b5da888bf85d54de53da372104`.

## Controlli applicativi

Eseguiti da backend con l'ambiente del progetto:

```powershell
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m pyright
.venv/Scripts/python.exe -m pytest -q
```

Ruff superato; 67 file gia formattati; Pyright 0 errori e 0 warning; pytest **255 passati**, un avviso preesistente Starlette/httpx (8,97 secondi). I test includono roundtrip Alembic su DB temporanei. Nessun comando di migrazione e stato applicato al DB locale; nessuna ricerca live o azione economica eseguita.

## Controlli documentali

Verifica automatica dei target Markdown relativi nei README e nelle schede: completata prima del commit, includendo indice, fonti, template e questo registro. I link esterni e lo schema chatgpt-conversation non sono stati interrogati via rete dal controllo link.

Confronto dei corpi originali delle otto sezioni 09.1–09.8 con le nuove pagine: conservati, con chiarimento del riferimento all'artefatto Crossref non tracciato. Specifica Execution Planning conservata e file originale invariato. Nessun sorgente, test, dipendenza o migrazione modificato.

`git diff --check` e controllo del diff staged eseguiti prima della pubblicazione. Scansione dei documenti per pattern di chiavi private, token GitHub, chiavi AWS e token sk- senza corrispondenze; controllo limitato a pattern noti e revisione del diff, non una prova assoluta di assenza di segreti. Sono inclusi soltanto README e documentazione milestone.

## Pubblicazione

Commit documentale e push sono operazioni successive a questo registro; hash ed esito vengono comunicati nel resoconto finale. Non viene attribuito preventivamente un esito al push. I dati storici non verificabili rimangono espliciti in SOURCES.md.
