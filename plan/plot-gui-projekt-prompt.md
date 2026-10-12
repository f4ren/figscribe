# Projekt-Prompt: Plotwerk (Arbeitstitel)

## Ziel

Baue eine schlanke Desktop-GUI für wissenschaftliche Plots, mit der man Plots interaktiv erstellt und feinjustiert und die als Ergebnis **sauberen, eigenständigen Python-Code** (Matplotlib) erzeugt statt einer proprietären Projektdatei.

Zielgruppe: Wissenschaftler und Ingenieure, die Origin zu unübersichtlich finden, für das Feintuning von Plots aber nicht alles von Hand in Matplotlib schreiben wollen.

## Architekturprinzip (verbindlich)

**Das deklarative Plot-Modell ist die einzige Quelle der Wahrheit.**

```
Plot-Modell (Dataclasses, serialisierbar als JSON)
   │
   ├──> Renderer: Modell -> Matplotlib-Figure (für GUI-Vorschau UND Export)
   ├──> Codegenerator: Modell -> eigenständiges Python-Skript
   └──> Persistenz: Modell <-> JSON-Projektdatei
GUI: liest und verändert ausschließlich das Modell (über Commands, siehe Undo/Redo)
```

Regeln:
- Die GUI manipuliert niemals Matplotlib-Objekte direkt dauerhaft. Jede Änderung läuft als Command über das Modell, danach wird neu gerendert.
- Vorschau und Export verwenden denselben Renderer. Was man sieht, ist exakt das, was exportiert wird (bei gleicher Figure-Größe und DPI).
- Der generierte Code muss ohne Plotwerk lauffähig sein und denselben Plot erzeugen wie der Renderer.
- Generierten Code wieder einzulesen ist **kein** Ziel. Nutzer dürfen den Code frei weiterbearbeiten, danach gehört er ihnen.

## Plot-Modell (erster Entwurf, darf verfeinert werden)

- `Project`: Liste von `Figure`, Liste von `DataSource`, Metadaten (Version, Erstellungsdatum)
- `DataSource`: Pfad, Format (CSV, HDF5, NPY/NPZ), Import-Optionen (Trennzeichen, Header-Zeile, HDF5-Dataset-Pfad), SHA-256 der Datei
- `Figure`: Größe in mm, DPI, Stylesheet, Layout (Grid aus Zeilen und Spalten, geteilte Achsen)
- `Axes`: Position im Grid, x/y-Label (LaTeX erlaubt), Einheiten, Skala (linear/log/symlog), Limits (auto oder fix), Ticks, zweite y-Achse optional, Legende (Position, sichtbar, Frame)
- `Artist` (Union-Typ):
  - `LinePlot`, `ScatterPlot`, `ErrorbarPlot` (x, y, xerr, yerr als Spaltenreferenzen)
  - `Histogram` (Bins, Normierung)
  - `ImagePlot` / `ColorMesh` (2D-Daten, Colormap, Colorbar, Normierung)
  - `FitCurve` (Referenz auf Daten-Artist, Modellfunktion, Startwerte, Ergebnisparameter mit Unsicherheiten, optional Residuenpanel)
  - `Annotation` (Text, Position in Daten- oder Achsenkoordinaten, Pfeil optional)
- Stil-Eigenschaften pro Artist: Farbe, Linienstil, Marker, Linienbreite, Alpha, Label, z-order

Alle Modellklassen: typisiert, validierbar, verlustfrei JSON-serialisierbar mit Schema-Version für spätere Migrationen.

## Funktionsumfang MVP

1. **Datenimport**: CSV, HDF5, NPY/NPZ. Vorschau der Spalten, Auswahl von Spalten für x, y und Fehler. Keine Tabellenkalkulation, keine Spaltenformeln.
2. **Plotten**: die Artist-Typen aus dem Modell.
3. **Interaktion im Canvas**:
   - Element anklicken: wird ausgewählt, Eigenschaften erscheinen im Property-Panel
   - Legende, Annotationen und Labels per Drag verschieben
   - Zoomen und Pannen, aktuellen Ausschnitt als feste Limits übernehmen
4. **Property-Panel**: generisch aus den Modellfeldern erzeugt, wo sinnvoll mit spezialisierten Editoren (Farbwähler, Marker-Auswahl).
5. **Achsen**: log/linear, zweite y-Achse, LaTeX-Labels, Einheiten.
6. **Layouts**: Multi-Panel-Grid mit geteilten Achsen.
7. **Fits**: `scipy.optimize.curve_fit`, vordefinierte Modelle (linear, Polynom, Gauß, Lorentz, Exponentiell) plus benutzerdefinierter Ausdruck. Ausgabe: Parameter mit 1-sigma-Unsicherheiten, reduziertes Chi-Quadrat, optional Residuenplot.
8. **Undo/Redo**: Command-Pattern über alle Modelländerungen.
9. **Export**: PDF, SVG und PNG mit exakter Größe in mm.
10. **Codegenerierung**: ein Python-Skript mit
    - Header: Datum, Plotwerk-Version, Paketversionen, Datenpfade mit SHA-256
    - Datenladen, Plotten, Speichern in klar kommentierten Abschnitten
    - nur Standardabhängigkeiten (numpy, matplotlib, optional scipy, h5py)
11. **Stil-Templates**: Matplotlib-Stylesheets (`.mplstyle`), mitgeliefert: ein neutraler Standard und eine Vorlage im Journal-Stil (einspaltig ca. 85 mm, zweispaltig ca. 175 mm).

## Bewusste Nicht-Ziele

- Keine Tabellenkalkulation oder Datenbearbeitung
- Keine Statistiksuite
- Keine eigene Skriptsprache
- Kein Einlesen von generiertem oder fremdem Python-Code
- Kein Origin-Import im MVP (eventuell später für .opj über liborigin)

## Nicht-funktionale Anforderungen

- Pixelgleiche Übereinstimmung von Vorschau und Export
- Flüssige Interaktion bis ca. 10^6 Datenpunkte (Downsampling nur in der Vorschau, Export immer mit vollen Daten)
- Plattformen: Linux, Windows, macOS
- Reproduzierbarkeit: Projektdatei und generierter Code enthalten Datenhashes und Versionen

## Technischer Stack

- Python >= 3.11
- PySide6 (Qt) für die GUI, Matplotlib-Canvas über `FigureCanvasQTAgg`
- Matplotlib als einziger Renderer
- NumPy, SciPy, h5py
- Modell: Dataclasses oder pydantic (begründete Entscheidung treffen und dokumentieren)
- Tests: pytest, pytest-qt
- Packaging: `pyproject.toml`, später PyInstaller oder Briefcase für Installer
- Lizenz: offen lassen, im README als TODO markieren

## Vorgeschlagene Projektstruktur

```
plotwerk/
  model/        # Dataclasses, Validierung, JSON-(De)Serialisierung, Schema-Versionen
  render/       # Modell -> Matplotlib
  codegen/      # Modell -> Python-Skript
  io/           # Datenimport (CSV, HDF5, NPY)
  fit/          # Fit-Modelle und Ausführung
  commands/     # Command-Pattern, Undo/Redo
  gui/          # Hauptfenster, Canvas, Property-Panel, Dialoge
  styles/       # mitgelieferte .mplstyle-Dateien
tests/
examples/       # Beispieldaten und Beispielprojekte
```

## Teststrategie (wichtig)

1. **Modell-Roundtrip**: Modell -> JSON -> Modell ergibt Gleichheit.
2. **Codegen-Äquivalenz** (Kerntest): Für jedes Beispielprojekt
   - Renderer erzeugt PNG A
   - generiertes Skript wird in einem Subprozess ausgeführt und erzeugt PNG B
   - A und B müssen pixelgleich sein (oder innerhalb einer sehr kleinen, begründeten Toleranz)
3. **Bild-Regressionstests** für den Renderer mit Referenzbildern.
4. **Command-Tests**: jede Änderung ist per Undo exakt rückgängig zu machen.
5. **GUI-Smoke-Tests** mit pytest-qt.

## Meilensteine

1. **M1 Modell und Renderer**: Modell, JSON-Persistenz, Renderer für Linie, Scatter und Errorbar, Export. Noch keine GUI. Tests 1 und 3.
2. **M2 Codegenerator**: Codegen für alle M1-Features, Äquivalenztest (Test 2) grün.
3. **M3 GUI-Grundgerüst**: Hauptfenster, Datenimport-Dialog, Canvas, Auswahl per Klick, generisches Property-Panel, Undo/Redo.
4. **M4 Interaktion**: Drag für Legende, Labels und Annotationen, Zoom-Limits übernehmen.
5. **M5 Erweiterungen**: Multi-Panel-Layouts, zweite y-Achse, Histogramm, 2D-Plots, Colorbar.
6. **M6 Fits**: Fit-Dialog, Ergebnisanzeige, Residuenpanel, Codegen inklusive Fit.
7. **M7 Feinschliff**: Stil-Templates, Snapping und Ausrichtungshilfen, Packaging.

Jeder Meilenstein endet mit grünen Tests und einem lauffähigen Stand.

## Arbeitsweise für den Coding-Agent

- Vor M1: Plot-Modell als Code-Entwurf vorlegen und begründen, erst danach implementieren.
- Klein und testgetrieben arbeiten: erst Test, dann Implementierung.
- Architekturentscheidungen kurz in `docs/decisions.md` festhalten (Kontext, Entscheidung, Alternativen).
- Keine neuen Abhängigkeiten ohne Begründung.
- Bei Unklarheiten im Modell lieber nachfragen als raten.
- Generierter Code soll so aussehen, wie ihn ein erfahrener Mensch schreiben würde: lesbar, kommentiert, ohne Plotwerk-interne Hilfsfunktionen.

## Optional, nach dem MVP

- Natürlichsprachliche Eingabe über ein LLM, die **Commands auf das Modell** erzeugt (keinen Code), damit alles nachvollziehbar und per Undo rückgängig machbar bleibt.
- Import älterer Origin-Projekte (.opj) über liborigin.
- Live-Daten-Modus (Datei beobachten, Plot aktualisieren).
