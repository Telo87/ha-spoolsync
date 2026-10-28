# Changelog

## 0.2.0

- Ort in Spoolman: Steckt eine Spule laut Bambu Studio / Bambu Handy in einem AMS-Slot, wird das
  als Ort in Spoolman eingetragen (z. B. „<Druckername> – AMS 1 Slot 2“). Kommt sie heraus, wird der Ort
  wieder geleert – ein von Hand eingetragener Ort bleibt.
- Benachrichtigungen in Home Assistant: wenn die Anmeldung bei der Bambu-Cloud fehlt oder in
  weniger als 7 Tagen abläuft, eine Seite mehrmals hintereinander nicht erreichbar ist oder
  Änderungen nicht übernommen werden konnten. Abschaltbar in der Konfiguration. Die Oberfläche
  zeigt, bis wann die Anmeldung gilt.
- Die Verknüpfung der Spulen steht zusätzlich im Zusatzfeld „Bambu-Cloud-ID“ in Spoolman. Nach
  einer Neuinstallation findet SpoolSync die Paare darüber wieder.
- Spulen von Hand trennen oder verknüpfen: in der Spulenliste. Getrennte Paare werden nicht wieder
  automatisch zusammengeführt.
- Neue Spulen aus der Bambu-Cloud bekommen in Spoolman den Farbnamen von Bambu Lab, z. B.
  „ABS Azurblau“ (Sprache von Home Assistant). Die Farbtabelle wird einmal pro Woche geladen.
- Spulen mit offiziellem Bambu-Profil behalten es, wenn sich nur der Name ändert.

## 0.1.4

- Farbname im Namen: Ist der Filamentname in Spoolman ein Farbname (z. B. „Turquoise“), zeigen
  Bambu Studio und Bambu Handy die Spule als „PLA+ Turquoise“. Bestehende Spulen werden beim
  nächsten Abgleich angepasst.
- Der Anzeigename aus 0.1.3 entfällt wieder – die Bambu-Apps zeigen ihn nicht an.
- Filament wie „PLA+“ bekommt das Generic-Profil des Grundmaterials (Generic PLA).

## 0.1.3

- Farbname für die Bambu-Cloud: Ist der Filamentname in Spoolman ein Farbname (z. B.
  „Turquoise“), wird er als Anzeigename der Spule in die Bambu-Cloud übertragen. Ändert er sich in
  Spoolman, wird er neu übertragen. Die Richtung ist nur Spoolman → Bambu-Cloud.

## 0.1.2

- Bambu Studio / Bambu Handy zeigen als Materialtyp das Material (z. B. „PLA“) statt eines
  Farbnamens, wenn der Filamentname in Spoolman nur die Farbe ist. Bestehende Spulen werden beim
  nächsten Abgleich angepasst; der Filamentname in Spoolman bleibt unverändert.
- Filament anderer Hersteller wird mit dem passenden Generic-Profil verknüpft (z. B. „Generic
  PLA“). Nimmt die Cloud das Profil nicht an, wird die Spule ohne Profil gespeichert.

## 0.1.1

- Anmeldung mit E-Mail-Code: Der Code wird jetzt ausdrücklich bei Bambu Lab angefordert – bisher kam
  keine E-Mail an.
- Schlägt das Anfordern des Codes fehl, zeigt SpoolSync die Meldung von Bambu Lab an.
- Abgelaufener Code: Es wird automatisch ein neuer verschickt.

## 0.1.0

- Erste Version: Spulen zwischen Spoolman und der Filamentbibliothek der Bambu-Lab-Cloud in beide
  Richtungen abgleichen (Hersteller, Material, Bezeichnung, Farbe, Gesamt- und Restgewicht, Notiz).
- Neue Spulen werden auf der jeweils anderen Seite angelegt, gelöschte Spulen übernommen.
- Verbrauch der Bambu-Lab-Drucker aus den Druckaufträgen der Cloud abbuchen.
- Anmeldung mit E-Mail-Code und Zwei-Faktor-Code, Probelauf mit Liste der geplanten Änderungen.
