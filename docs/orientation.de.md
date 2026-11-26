# Sich zurechtfinden

Anmelden kannst du dich mit deinem Google-Konto, sofern du als aktive
Person erfasst bist. Alle Angemeldeten sehen alles ausser den Entwürfen
anderer.

## Navigation

- **Organisation**: der Anker-Kreis, von dem aus alles erreichbar ist.
- **Kreise**: der Kreis-Browser zeigt die Kreise ineinander. Ein Klick
  vergrössert einen Kreis, ein zweiter öffnet seine Seite; der Hintergrund
  oder Escape verkleinert wieder. "Meine Rollen" hebt deine Rollen hervor (auch die, die du ohne Zuweisung ausfüllst).
  Darunter steht dieselbe Struktur als Liste.
- **Dein Name** (oben rechts) öffnet ein Menü: deine Seite,
  Einstellungen, "API-Tokens", "Tactical Meeting einberufen",
  **Personen** (alle mit ihren Rollen), **Mailadressen**, Hilfe, für
  Admins "Verwaltung" (das Django-Admin) und Abmelden. Auf breiten Bildschirmen stehen **Personen** auch in der
  Navigation.
- **Vorschläge**: alle Vorschläge, gefiltert nach Status, Kreis (mit
  seinen Sub-Kreisen) und der Rolle, die sie ändern.
- **Geschichte**: was sich wann geändert hat; für einen Kreis mit seinen
  Rollen ("Mit Sub-Kreisen" auch, was darin ist) oder für eine Rolle, auf
  Wunsch mit den Zuweisungen und mit Links, Notizen, Metriken und Checklisten. Die
  Seiten der Kreise und Rollen verlinken ihre.
- **Suchen** findet Personen (nach Name, Kurzname und Mailadresse, mit ihren Kreisen),
  Rollen, Accountabilities, Domains, Policies, Links (nach Titel und
  Beschreibung), Notizen (nach Titel und Text), Checklisten-Punkte und
  Metriken, die alle eingegebenen Wörter enthalten. Die
  Beschreibung eines Links kann Stichwörter aufzählen, z.B. für einen
  Abschnitt des Handbuchs. "Auch Archiviertes und Inaktive" findet auch
  archivierte Rollen (mit ihren Texten, Links, Notizen,
  Checklisten-Punkten und Metriken), archivierte Policies und inaktive
  Personen, nach den aktuellen und markiert.

**Mailadressen** listet die Adressen aller mit einer Rolle, aller Circle
Leads, Facilitators, Secretaries und Circle Reps (bei unbesetzten Rollen
Facilitator und Secretary die Vertretung: Secretary oder Facilitator,
sonst die Circle Leads) und der Mitglieder jedes Kreises auf, zum
Kopieren in eine Mail ("Kopieren") oder um ihnen zu schreiben ("Neue
Mail"). Das Menü "…" eines Kreises und seine Rollen verlinken die
Adressen seiner Mitglieder.

## Tastenkürzel

| Kürzel | |
| --- | --- |
| <kbd>Alt-H</kbd> | Startseite: deine Personenseite |
| <kbd>Alt-O</kbd> | Organisation |
| <kbd>Alt-Q</kbd> | ins Suchfeld |

Fährst du mit der Maus über einen Link, zeigt er sein Kürzel.

## Kreise, Rollen und Personen

Ein **Kreis** zeigt Purpose, Strategie, Domains, Accountabilities, seine
Policies, seine Kernrollen und Meetings, offene Vorschläge, Checklisten
und Metriken, Links, Notizen, die Geschichte und seine Rollen mit ihren Role
Leads (wer eine Rolle ausfüllt, Verfassung 1.1; die Role Leads eines
Kreises sind die Circle Leads darin, 1.4). Gewählte Rollen, deren
Amtszeit innert 14 Tagen endet oder die niemand hat, sind mit "Wahl
fällig" markiert, hier und auf der Seite der Person, die sie hat.
"Mitglieder" im Menü "…" zeigt, wer welche Rollen des Kreises ausfüllt,
eine Spalte pro Mitglied (ein leerer Kreis, wo die Circle Leads eine
Rolle haben, die niemand hat), dann rechts in Grau unter "Andere" alle,
die nicht Mitglied sind. Die Circle Leads weisen direkt in der Tabelle zu, auch
Personen ausserhalb des Kreises, ändern den Fokus und entfernen: Mit der
Maus über einer Zelle oder beim Antippen erscheinen die Knöpfe.

Eine **Rolle** zeigt Purpose, Domains, Accountabilities, ihre Policies,
wer sie hat (mit Fokus und Amtszeit, die Circle Leads weisen hier zu und
entfernen), Checklisten, Metriken, Links und Notizen. Alle können die Domains,
Accountabilities, Links und Notizen an ihren Griffen in eine andere Reihenfolge ziehen, das
ist keine Änderung der Governance. Eine Domain mit Policies
verlinkt sie ("2 Policies") und klappt sie auf; die Karte Policies
erscheint nur, wenn die Rolle eigene hat. "Domains und Policies, die
diese Rolle betreffen" im Menü "…" zeigt, was von aussen für sie gilt: die
Domains und Policies ihrer Kreise und die Domains von deren Rollen, vom
äussersten Kreis nach innen. Ihre Meetings, die ihres Kreises und die, zu denen sie eingeladen war (siehe [Meetings](meetings.de.md)), stehen im Menü "…".
Rollen ohne Zuweisung füllen die Circle Leads aus, ausser der Rolle Circle Rep; ist niemand der Rolle Circle Lead zugewiesen, die Circle Leads des übergeordneten Kreises;
die Rolle Secretary füllt Facilitator aus und umgekehrt, erst ohne beide
die Circle Leads (Verfassung 5.3.6).
Die Seiten zeigen sie mit "Als Circle Lead" ("Als Facilitator", "Als
Secretary"; die der Rolle, die ihres Kreises,
der Kreis-Browser, deine Personenseite, das Zuweisen, das Einberufen eines
Tactical Meetings, der Markdown-Export).

**Deine Personenseite**, die Startseite, zeigt deine Rollen (auch die ohne Zuweisung, die du
ausfüllst, markiert "Als Circle Lead" oder ähnlich), deine Entwürfe und Spannungen,
Vorschläge, die auf deine Antwort warten, deine Meetings und deine
Einstellungen: Name, Kurzname (im Menü oben), Sprache (Deutsch oder
Englisch) und Mails. "Einstellungen" im Menü mit deinem Namen ändert sie
in einem Formular; die Mailadresse wird nur angezeigt, damit meldest du
dich an.

Laufende Meetings, an denen du teilnimmst, stehen oben auf jeder Seite.

## Zurückblicken

Jede Rolle und jeder Kreis hat eine Geschichte: die Vorschläge, die sie
geändert haben, mit Spannung und Vergleich, und was sich ohne Vorschlag
geändert hat (z.B. in GlassFrog; die Policies einer Rolle für ihre
Domains als "Direkt geändert" und von wem). Die Seite der Rolle zeigt das Neueste
davon und ihre früheren Namen. "Stand anzeigen" zeigt die
Struktur an einem früheren Tag, zurück bis 2018.

## Texte

Texte sind einfaches Markdown (`**fett**`, Listen mit `-`, Links). Mit
`@` erwähnst du eine Rolle: das Feld schlägt Namen vor, der Link zeigt
immer den aktuellen Namen der Rolle. Der ganze Name einer Rolle nach `@`
wird auch beim Speichern zum Link; heissen mehrere Rollen so (wie
Facilitator), die des Kreises (des Vorschlags, der Spannung oder des
Meetings).

Kurze Formulare (Strategie, Metriken, Checklisten-Punkte, Links, Notizen, Policies
einer Domain, Einstellungen, Zuweisen, Fokus und Entfernen, die Spannung
eines Entwurfs) öffnen sich über der Seite.
Escape schliesst sie; sobald etwas eingegeben ist, erst beim zweiten Mal.

## Mails

Du erhältst Mails zu dem, was in den Kreisen geschieht, in denen du eine
Rolle hast, und zu deinen Rollen und Vorschlägen; in deinen
Einstellungen kannst du Mails zu allem in allen Kreisen wählen.
[Mails](mails.de.md) listet auf, welche Mails an wen gehen.

## API

Für Skripte und andere Tools: unter "API-Tokens" (im Menü deines Namens) erstellst du ein Token (nur
lesen oder lesen und schreiben, gültig bis 30 Tage nach der letzten
Verwendung); "Löschen" dort widerruft es sofort. Die API liest die
Struktur, Vorschläge und Meetings, legt Entwürfe an und verwaltet die Links und Notizen von Rollen und Kreisen; ihre Dokumentation steht
unter `/api/docs`.

Das Kommandozeilen-Tool `gov` nutzt die API und holt sich sein Token
selbst (`gov login`, im Browser bestätigen). Es zeigt Kreise, Rollen,
Vorschläge und Meetings, sucht, bereitet Entwürfe vor und verwaltet Links, Notizen, Metriken und Checklisten-Punkte (`gov links`, `gov notes`, `gov metrics`, `gov checklist`); wie du es und die mitgelieferten
Claude-Code-Skills installierst, steht auf der Seite "API-Tokens".
`gov logout` widerruft das Token, das `gov` auf diesem Computer
verwendet, `gov tokens` listet deine Tokens auf und
`gov tokens delete ID` widerruft sie.
