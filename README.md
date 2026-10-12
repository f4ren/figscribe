# figscribe

Schlanke Desktop-GUI für wissenschaftliche Plots: Plots interaktiv erstellen und
feinjustieren, Ergebnis ist **sauberer, eigenständiger Python-Code** (Matplotlib)
statt einer proprietären Projektdatei.

Zielgruppe: Wissenschaftler und Ingenieure, die Origin zu unübersichtlich finden,
für das Feintuning von Plots aber nicht alles von Hand in Matplotlib schreiben wollen.

## Status

**Sehr früh — Planungsphase.** Auf PyPI liegt bislang nur ein Platzhalter-Release,
um den Namen zu belegen. Es gibt noch keine nutzbare Funktionalität.

Der ausgearbeitete Projektplan liegt in [`plan/`](plan/).

## Architekturprinzip

Das deklarative Plot-Modell ist die einzige Quelle der Wahrheit:

```
Plot-Modell (typisiert, JSON-serialisierbar)
   ├──> Renderer:       Modell -> Matplotlib-Figure (GUI-Vorschau UND Export)
   ├──> Codegenerator:  Modell -> eigenständiges Python-Skript
   └──> Persistenz:     Modell <-> JSON-Projektdatei
```

Die GUI liest und verändert ausschließlich das Modell (über Commands, mit Undo/Redo).
Vorschau und Export nutzen denselben Renderer, der generierte Code erzeugt denselben
Plot und läuft ohne figscribe.

## Technischer Stack

Python >= 3.11, PySide6, Matplotlib, NumPy, SciPy, h5py.

## Lizenz

TODO: noch nicht festgelegt.
