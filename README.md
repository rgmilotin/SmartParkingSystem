Smart Parking System

Sistem inteligent de administrare a unei parcări, realizat cu Arduino Nano, Raspberry Pi, senzori ultrasonici, servomotoare, cameră pentru recunoașterea numerelor de înmatriculare, bază de date MySQL/MariaDB și o aplicație web Flask pentru calcularea și confirmarea plății.

Proiectul automatizează principalele operații ale unei parcări:

detectarea unei mașini la intrare;
fotografierea și recunoașterea numărului de înmatriculare;
înregistrarea intrării în baza de date;
controlul barierei de intrare;
detectarea ocupării locurilor de parcare;
afișarea numărului de locuri libere;
calcularea costului parcării;
confirmarea plății dintr-o interfață web;
autorizarea și controlul barierei de ieșire.

Sistemul este împărțit în trei programe principale, fiecare având un rol bine definit.

## `Parcare_Arduino.ino`

Programul încărcat pe Arduino Nano controlează partea fizică a parcării.

Acesta:

* citește cei patru senzori ultrasonici;
* detectează mașinile la intrare și ieșire;
* stabilește dacă cele două locuri sunt libere sau ocupate;
* calculează și afișează pe LCD numărul locurilor disponibile;
* controlează servomotoarele celor două bariere;
* trimite către Raspberry Pi cererea de validare a unei mașini;
* primește comenzile de acceptare, respingere sau autorizare a ieșirii;
* gestionează automat deschiderea și închiderea barierelor.

Logica este organizată prin stări separate pentru intrare și ieșire, astfel încât senzorii, LCD-ul și comunicarea serială să poată fi gestionate în paralel.

## `Principal.py`

Programul principal rulează pe Raspberry Pi și coordonează camera, OCR-ul, baza de date și comunicarea cu Arduino.

Acesta:

* primește de la Arduino semnalul că o mașină a ajuns la intrare;
* capturează și procesează imaginea folosind OpenCV;
* recunoaște numărul de înmatriculare cu Tesseract OCR;
* corectează erorile frecvente de recunoaștere;
* verifică dacă numărul este valid și dacă mașina are deja un log activ;
* înregistrează intrarea în baza de date;
* trimite către Arduino acces permis sau respins;
* verifică plățile confirmate și autorizează ieșirea.

Programul salvează și imagini intermediare în directorul `debug_ocr`, pentru calibrarea și depanarea procesului OCR.

## `App_Parcare.py`

Programul pornește o aplicație web Flask pentru verificarea și confirmarea plății parcării.

Acesta:

* permite căutarea unei mașini după numărul de înmatriculare;
* afișează ora intrării, durata, datele clientului și suma de plată;
* calculează costul folosind tariful configurat;
* oferă acces gratuit angajaților și numerelor speciale;
* salvează plata, durata și timpul plecării;
* generează cererea de ieșire care va fi preluată de `Principal.py`.

Aplicația poate fi accesată dintr-un browser aflat în aceeași rețea cu Raspberry Pi, folosind portul `5000`.

## Comunicarea dintre programe

Cele trei programe comunică prin:

* conexiunea serială dintre Arduino și Raspberry Pi;
* baza de date MySQL/MariaDB folosită de `Principal.py` și `App_Parcare.py`.

Fluxul general este:

Arduino detectează mașina
        ↓
Principal.py recunoaște și înregistrează numărul
        ↓
App_Parcare.py calculează și confirmă plata
        ↓
Principal.py detectează plata
        ↓
Arduino deschide bariera de ieșire
