# Changelog

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
