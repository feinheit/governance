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
- **Personen**: alle mit ihren Rollen.
- **Vorschläge**: alle Vorschläge, nach Status gefiltert.
- **Geschichte**: was sich wann geändert hat, auf Wunsch mit den
  Zuweisungen.
- **Suchen** findet Rollen, Accountabilities, Domains und Policies, die
  alle eingegebenen Wörter enthalten.

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
Policies, seine Kernrollen und Meetings, offene Vorschläge, anstehende
Wahlen, Checklisten und Metriken, Links, die Geschichte und seine Rollen
mit Besetzung.

Eine **Rolle** zeigt Purpose, Domains, Accountabilities, ihre Policies,
wer sie hat (mit Fokus und Amtszeit, die Circle Leads weisen hier zu und
entfernen), Checklisten, Metriken und Links. Eine Domain mit Policies
verlinkt sie ("2 Policies") und klappt sie auf. "Domains und Policies,
die diese Rolle betreffen" zeigt, was von aussen für sie gilt: die
Domains und Policies ihrer Kreise und die Domains von deren Rollen, vom
äussersten Kreis nach innen. Ihre Meetings (selten, siehe [Meetings](meetings.de.md))
stehen im Menü "…".
Unbesetzte Rollen haben die Circle Leads, ausser dem Circle Rep; einen
unbesetzten Circle Lead die des übergeordneten Kreises.

**Deine Personenseite**, die Startseite, zeigt deine Rollen, deine Entwürfe und Spannungen,
Vorschläge, die auf deine Antwort warten, deine Meetings und deine
Einstellungen: Mails und Sprache (Deutsch oder Englisch).

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
Wünschen nach einem Meeting, der Secretary von letzteren, und auf deine
Fragen kommt die Antwort per Mail. Auf deiner Personenseite kannst du dich über alles in
allen Kreisen informieren lassen. [Mails](mails.de.md) listet alle auf.

## API

Für Skripte und andere Tools: unter "API" erstellst du ein Token (nur
lesen oder lesen und schreiben, gültig bis 30 Tage nach der letzten
Verwendung). Die API liest die
Struktur und Vorschläge und legt Entwürfe an; ihre Dokumentation steht
unter `/api/docs`.

Das Kommandozeilen-Tool `gov` nutzt die API und holt sich sein Token
selbst (`gov login`, im Browser bestätigen). Es zeigt Kreise, Rollen und
Vorschläge, sucht, und bereitet Entwürfe vor; wie du es installierst,
steht auf der Seite "API".
