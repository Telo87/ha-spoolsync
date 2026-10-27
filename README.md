<img src="spoolsync/logo.png" alt="SpoolSync" width="250">

# SpoolSync – Home Assistant Add-on

[![Version](https://img.shields.io/badge/version-0.1.3-blue)](spoolsync/CHANGELOG.md)

Gleicht die Filamentspulen zwischen [Spoolman](https://github.com/Donkie/Spoolman) und der
Filamentbibliothek der Bambu-Lab-Cloud (Bambu Studio, Bambu Handy) in beide Richtungen ab:
Hersteller, Material, Farbe, Gesamt- und Restgewicht, Notiz. Neue Spulen erscheinen auf der jeweils
anderen Seite, der Verbrauch der Bambu-Lab-Drucker wird aus den Druckaufträgen abgebucht.

## Installation

1. In Home Assistant: **Einstellungen → Add-ons → Add-on Store → ⋮ → Repositories** und
   `https://github.com/Telo87/ha-spoolsync` hinzufügen.
2. **SpoolSync** installieren, die Adresse von Spoolman eintragen und starten.
3. Über **Öffnen** mit dem Bambu-Lab-Konto anmelden und den Probelauf prüfen.

Details: [Dokumentation](spoolsync/DOCS.md)

> Die Cloud-Schnittstelle von Bambu Lab ist nicht offiziell dokumentiert und kann sich ändern.

## Lizenz

MIT
