# Sich zurechtfinden

Anmelden kannst du dich mit deinem Google-Konto, sofern du als aktive
Person erfasst bist. Alle Angemeldeten sehen alles ausser den Entwürfen
anderer.

## Navigation

- **Organisation**: der Anker-Kreis, von dem aus alles erreichbar ist.
- **Kreise**: der Kreis-Browser zeigt die Kreise ineinander. Ein Klick
  vergrössert einen Kreis, ein zweiter öffnet seine Seite; der Hintergrund
  oder Escape verkleinert wieder. "Meine Rollen" hebt deine Rollen hervor.
  Darunter steht dieselbe Struktur als Liste.
- **Dein Name** (oben rechts) öffnet ein Menü: deine Seite, "Tactical
  Meeting einberufen",
  **Personen** (alle mit ihren Rollen), **Mailadressen**, Hilfe, API und
  Abmelden. Auf breiten Bildschirmen stehen **Personen** auch in der
  Navigation.
- **Vorschläge**: alle Vorschläge, gefiltert nach Status, Kreis (mit
  seinen Sub-Kreisen) und der Rolle, die sie ändern.
- **Geschichte**: was sich wann geändert hat; für einen Kreis mit seinen
  Rollen ("Mit Sub-Kreisen" auch, was darin ist) oder für eine Rolle, auf
  Wunsch mit den Zuweisungen und mit Links, Metriken und Checklisten. Die
  Seiten der Kreise und Rollen verlinken ihre.
- **Suchen** findet Rollen, Accountabilities, Domains und Policies, die
  alle eingegebenen Wörter enthalten.

**Mailadressen** listet die Adressen aller mit einer Rolle, aller Circle
Leads, Facilitators, Secretaries und Circle Reps (bei unbesetzten Rollen
Facilitator und Secretary die Vertretung: Secretary oder Facilitator,
sonst die Circle Leads) und der Mitglieder jedes Kreises auf, zum
Kopieren in eine Mail ("Kopieren") oder um ihnen zu schreiben ("Neue
Mail"). Das Menü "…" eines Kreises verlinkt seine Mitglieder.

## Tastenkürzel

| Kürzel | |
| --- | --- |
| <kbd>Alt-H</kbd> | Startseite: deine Personenseite |
| <kbd>Alt-O</kbd> | Organisation |
| <kbd>Alt-Q</kbd> | ins Suchfeld |

Auf dem Mac <kbd>Ctrl</kbd> statt <kbd>Alt</kbd>. Fährst du mit der Maus
über einen Link, zeigt er sein Kürzel.

## Kreise, Rollen und Personen

Ein **Kreis** zeigt Purpose, Strategie, Domains, Accountabilities, seine
Policies, seine Kernrollen und Meetings, offene Vorschläge, Checklisten
und Metriken, Links, die Geschichte und seine Rollen mit ihren Role
Leads (wer eine Rolle ausfüllt, Verfassung 1.1; die Role Leads eines
Kreises sind die Circle Leads darin, 1.4). Gewählte Rollen, deren
Amtszeit innert 14 Tagen endet oder die niemand hat, sind mit "Wahl
fällig" markiert, hier und auf der Seite der Person, die sie hat.

Eine **Rolle** zeigt Purpose, Domains, Accountabilities, ihre Policies,
wer sie hat (mit Fokus und Amtszeit, die Circle Leads weisen hier zu und
entfernen), Checklisten, Metriken und Links. Alle können die Domains und
Accountabilities an ihren Griffen in eine andere Reihenfolge ziehen, das
ist keine Änderung der Governance. Eine Domain mit Policies
verlinkt sie ("2 Policies") und klappt sie auf; die Karte Policies
erscheint nur, wenn die Rolle eigene hat. "Domains und Policies, die
diese Rolle betreffen" im Menü "…" zeigt, was von aussen für sie gilt: die
Domains und Policies ihrer Kreise und die Domains von deren Rollen, vom
äussersten Kreis nach innen. Ihre Meetings, die ihres Kreises und die, zu denen sie eingeladen war (siehe [Meetings](meetings.de.md)), stehen im Menü "…".
Unbesetzte Rollen haben die Circle Leads, ausser der Rolle Circle Rep; ist die Rolle Circle Lead unbesetzt, haben sie die Circle Leads des übergeordneten Kreises.

**Deine Personenseite**, die Startseite, zeigt deine Rollen, deine Entwürfe und Spannungen,
Vorschläge, die auf deine Antwort warten, deine Meetings und deine
Einstellungen: Name, Kurzname (im Menü oben), Sprache (Deutsch oder
Englisch) und Mails. "Einstellungen" im Menü mit deinem Namen ändert sie
in einem Formular; die Mailadresse wird nur angezeigt, damit meldest du
dich an.

Laufende Meetings, an denen du teilnimmst, stehen oben auf jeder Seite.

## Zurückblicken

Jede Rolle und jeder Kreis hat eine Geschichte: die Vorschläge, die sie
geändert haben, mit Spannung und Vergleich, und was sich ohne Vorschlag
geändert hat (z.B. in GlassFrog). Die Seite der Rolle zeigt das Neueste
davon und ihre früheren Namen. "Stand anzeigen" zeigt die
Struktur an einem früheren Tag, zurück bis 2018.

## Texte

Texte sind einfaches Markdown (`**fett**`, Listen mit `-`, Links). Mit
`@` erwähnst du eine Rolle: das Feld schlägt Namen vor, der Link zeigt
immer den aktuellen Namen der Rolle.

Kurze Formulare (Strategie, Metriken, Checklisten-Punkte, Links, Policies
einer Domain, Einstellungen, Zuweisen, Fokus und Entfernen, die Spannung
eines Entwurfs) öffnen sich über der Seite.
Escape schliesst sie; sobald etwas eingegeben ist, erst beim zweiten Mal.

## Mails

Du erhältst Mails zu den Kreisen, in denen du Mitglied bist, also eine
Rolle hast (auch als Circle Lead oder Circle Rep eines Sub-Kreises):
veröffentlichte und angenommene Vorschläge, geänderte Policies einer
Domain und die Ergebnisse von Meetings. Du erfährst auch von Rollen, die
du erhältst oder abgibst, von Änderungen deines Fokus und als Secretary, wer deinem Kreis beitritt
oder ihn verlässt. Wer einen Vorschlag macht, erfährt von Fragen und
Wünschen nach einem Meeting, wer Secretary ist, von letzteren, und auf deine
Fragen kommt die Antwort per Mail. In deinen Einstellungen kannst du
Mails zu allem in allen Kreisen wählen. [Mails](mails.de.md) listet alle auf.

## API

Für Skripte und andere Tools: unter "API" (im Menü deines Namens) erstellst du ein Token (nur
lesen oder lesen und schreiben, gültig bis 30 Tage nach der letzten
Verwendung). Die API liest die
Struktur und Vorschläge, legt Entwürfe an und verwaltet die Links von Rollen und Kreisen; ihre Dokumentation steht
unter `/api/docs`.

Das Kommandozeilen-Tool `gov` nutzt die API und holt sich sein Token
selbst (`gov login`, im Browser bestätigen). Es zeigt Kreise, Rollen und
Vorschläge, sucht, bereitet Entwürfe vor und verwaltet Links (`gov links`); wie du es installierst,
steht auf der Seite "API".
