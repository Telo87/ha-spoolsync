# SpoolSync

SpoolSync gleicht die Filamentspulen zwischen **Spoolman** und der **Filamentbibliothek der
Bambu-Lab-Cloud** (die Spulenliste in Bambu Studio und Bambu Handy) in beide Richtungen ab. So
bleibt Spoolman die zentrale Verwaltung für alle Drucker, und Bambu Studio zeigt trotzdem immer
dieselben Spulen mit demselben Restgewicht.

## Was abgeglichen wird

| Angabe | Spoolman | Bambu-Cloud |
|---|---|---|
| Hersteller | Hersteller des Filaments | Hersteller |
| Material | Material des Filaments | Typ |
| Bezeichnung | Name des Filaments | Name |
| Farbe | Farbe des Filaments | Farbe |
| Gesamtgewicht | Anfangsgewicht der Spule | Gesamtgewicht |
| Restgewicht | Restgewicht der Spule | Restgewicht |
| Notiz | Kommentar der Spule | Notiz |

- **Neue Spulen:** Eine Spule, die es nur auf einer Seite gibt, wird auf der anderen angelegt.
  Fehlende Hersteller und Filamente legt SpoolSync in Spoolman selbst an.
- **Geänderte Werte:** Gewinnt die Seite, auf der sich der Wert seit dem letzten Abgleich geändert
  hat. Wurde derselbe Wert auf beiden Seiten geändert, gilt beim Restgewicht der kleinere Wert
  (Filament wird nur verbraucht), sonst die Seite aus „Vorrang bei Konflikten“.
- **Gelöschte Spulen** (abschaltbar): In Spoolman archiviert oder gelöscht → aus der Bambu-Cloud
  entfernt. In der Bambu-Cloud gelöscht → in Spoolman archiviert (nie gelöscht). Fehlt auf einer
  Seite plötzlich der Großteil der Spulen, werden Löschungen in diesem Durchlauf nicht übernommen.
- **Erster Abgleich:** Spulen, die es auf beiden Seiten schon gibt, werden anhand von Material,
  Farbe, Hersteller, Bezeichnung und Gewicht einander zugeordnet statt doppelt angelegt.

## Verbrauch beim Drucken

- **Andere Drucker (z. B. über OctoPrint, Klipper):** Bucht deren Spoolman-Anbindung den Verbrauch
  in Spoolman, überträgt SpoolSync das neue Restgewicht beim nächsten Abgleich in die Bambu-Cloud.
- **Bambu-Lab-Drucker:** Die Bambu-Cloud zieht bei Spulen ohne RFID-Chip selbst nichts ab. Mit
  „Drucke der Bambu-Lab-Drucker abbuchen“ liest SpoolSync die abgeschlossenen Druckaufträge und
  zieht die verbrauchten Gramm in Spoolman von der Spule ab, die in Bambu Studio / Bambu Handy dem
  benutzten AMS-Slot zugeordnet ist (Spulenliste → Spule → Slot zuordnen). Danach geht der Wert wie
  jede andere Änderung zurück in die Cloud.
  - Spulen mit RFID-Chip meldet das AMS selbst – sie werden nicht zusätzlich abgezogen.
  - Ist das Restgewicht schon um etwa die Druckmenge gesunken, wird nicht doppelt gebucht.
  - Gebucht werden nur Drucke, die nach dem ersten Start von SpoolSync enden. Bei abgebrochenen
    Drucken ist der Verbrauch nicht bekannt; sie werden nicht gebucht.
  - Bucht bereits ein anderes Werkzeug den Verbrauch dieser Drucker in Spoolman, die Option
    ausschalten.

## Einrichtung

1. In der Konfiguration die **Adresse von Spoolman** eintragen (z. B. `http://<Adresse von Home
   Assistant>:7912`).
2. SpoolSync öffnen und mit dem **Bambu-Lab-Konto** anmelden. Bambu Lab schickt meist einen Code
   per E-Mail; bei aktivierter Zwei-Faktor-Anmeldung den Code der Authenticator-App eingeben. Das
   Passwort wird nicht gespeichert, nur die Anmeldung (gültig etwa 90 Tage, danach neu anmelden).
3. Unter **Geplante Änderungen** prüfen, was SpoolSync tun würde. Passt alles, mit **Jetzt
   abgleichen** übernehmen.
4. Wenn der Probelauf stimmt, in der Konfiguration **Automatisch abgleichen** einschalten.

## Hinweise

- Die Schnittstelle der Bambu-Lab-Cloud ist nicht offiziell dokumentiert. Ändert Bambu Lab sie,
  kann der Abgleich ausfallen, bis SpoolSync angepasst ist.
- Spoolman ordnet Farbe, Material und Hersteller dem Filament zu, nicht der einzelnen Spule. Ändert
  sich eine dieser Angaben in der Bambu-Cloud, bekommt die Spule in Spoolman das passende Filament
  (wird bei Bedarf angelegt) – andere Spulen desselben Filaments bleiben unverändert.
- SpoolSync merkt sich die Zuordnung der Spulen in `/data/links.json` des Add-ons.
