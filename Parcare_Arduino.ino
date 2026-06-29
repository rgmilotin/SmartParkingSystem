#include <LiquidCrystal_I2C.h>
#include <Wire.h>
#include <Servo.h>

// LCD I2C 20x4, adresa uzuala 0x27
LiquidCrystal_I2C lcd(0x27, 20, 4);

Servo servoIntrare;
Servo servoIesire;

// ---------------- PINI ----------------
const byte TRIG_INTRARE = 2;
const byte ECHO_INTRARE = 3;

const byte TRIG_LOC_1 = 4;
const byte ECHO_LOC_1 = 5;

const byte TRIG_LOC_2 = 6;
const byte ECHO_LOC_2 = 7;

const byte PIN_SERVO_INTRARE = 9;
const byte PIN_SERVO_IESIRE = 10;

const byte TRIG_IESIRE = 11;
const byte ECHO_IESIRE = 12;

// ---------------- PRAGURI DISTANTA ----------------
const int PRAG_INTRARE_CM = 5;
const int PRAG_IESIRE_CM = 5;
const int PRAG_LOC_CM = 10;

// ---------------- SERVO INTRARE ----------------
const int INTRARE_INCHISA = 0;
const int INTRARE_DESCHISA = 90;

// ---------------- SERVO IESIRE ----------------
// Folosim doar doua valori:
const int IESIRE_STOP = 90;
const int IESIRE_DESCHIDE = 180;

// Dupa ce masina este detectata la iesire si a platit,
// servo-ul sta pe 180 timp de 5 secunde, apoi revine la 90.
const unsigned long TIMP_DESCHIDERE_IESIRE = 5000;

// ---------------- TIMPI ----------------
const unsigned long INTERVAL_SENZORI = 300;
const unsigned long TIMP_MAXIM_VALIDARE = 10000;
const unsigned long TIMP_MAXIM_IESIRE_DUPA_PLATA = 60000;
const unsigned long TIMP_FARA_MASINA_INTRARE = 2000;

// ---------------- DEBUG ----------------
const bool DEBUG_SERIAL = true;

// Raspberry Pi -> Arduino:
// 'A' = acces intrare acceptat
// 'R' = acces intrare respins
// 'I' = iesire aprobata dupa plata in app
//
// Arduino -> Raspberry Pi:
// 'C' = masina detectata la intrare, porneste camera si validarea

enum StareIntrare
{
  INTRARE_GATA,
  ASTEAPTA_VALIDARE,
  BARIERA_INTRARE_DESCHISA
};

enum StareIesire
{
  IESIRE_INCHISA,
  IESIRE_DESCHISA_5_SECUNDE
};

StareIntrare stareIntrare = INTRARE_GATA;
StareIesire stareIesire = IESIRE_INCHISA;

bool masinaLaIntrare = false;
bool masinaLaIntrareAnterior = false;

bool masinaLaIesire = false;

bool loc1Ocupat = false;
bool loc2Ocupat = false;

bool iesireAprobataDinPython = false;
bool mesajPlataIesireAfisat = false;

int locuriLibere = 2;
int locuriLibereAnterior = -1;

unsigned long ultimaCitireSenzori = 0;

unsigned long timpStareIntrare = 0;
unsigned long timpStareIesire = 0;

unsigned long timpAprobareIesire = 0;
unsigned long timpFaraMasinaIntrare = 0;

bool mesajTemporarActiv = false;
unsigned long inceputMesaj = 0;
unsigned long durataMesaj = 0;

long citesteDistanta(byte trigPin, byte echoPin)
{
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  unsigned long durata = pulseIn(echoPin, HIGH, 25000UL);

  if (durata == 0)
  {
    return 999;
  }

  return durata / 58;
}

void debugPrint(String mesaj)
{
  if (DEBUG_SERIAL)
  {
    Serial.println(mesaj);
  }
}

void afiseazaStareaParcarii()
{
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("Bine ati venit!");

  lcd.setCursor(0, 1);
  lcd.print("Locuri libere: ");
  lcd.print(locuriLibere);

  lcd.setCursor(0, 2);
  lcd.print("Loc 1: ");
  lcd.print(loc1Ocupat ? "OCUPAT" : "LIBER ");

  lcd.setCursor(0, 3);
  lcd.print("Loc 2: ");
  lcd.print(loc2Ocupat ? "OCUPAT" : "LIBER ");
}

void afiseazaMesaj(const char *linia1,
                   const char *linia2,
                   const char *linia3,
                   const char *linia4,
                   unsigned long durata)
{
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print(linia1);

  lcd.setCursor(0, 1);
  lcd.print(linia2);

  lcd.setCursor(0, 2);
  lcd.print(linia3);

  lcd.setCursor(0, 3);
  lcd.print(linia4);

  mesajTemporarActiv = true;
  inceputMesaj = millis();
  durataMesaj = durata;
}

void actualizeazaSenzorii()
{
  long distantaIntrare = citesteDistanta(TRIG_INTRARE, ECHO_INTRARE);
  delay(15);

  long distantaLoc1 = citesteDistanta(TRIG_LOC_1, ECHO_LOC_1);
  delay(15);

  long distantaLoc2 = citesteDistanta(TRIG_LOC_2, ECHO_LOC_2);
  delay(15);

  long distantaIesire = citesteDistanta(TRIG_IESIRE, ECHO_IESIRE);

  masinaLaIntrare = distantaIntrare <= PRAG_INTRARE_CM;
  masinaLaIesire = distantaIesire <= PRAG_IESIRE_CM;

  loc1Ocupat = distantaLoc1 <= PRAG_LOC_CM;
  loc2Ocupat = distantaLoc2 <= PRAG_LOC_CM;

  locuriLibere = 0;

  if (!loc1Ocupat)
  {
    locuriLibere++;
  }

  if (!loc2Ocupat)
  {
    locuriLibere++;
  }

  if (DEBUG_SERIAL)
  {
    Serial.print("Iesire: ");
    Serial.print(distantaIesire);
    Serial.print(" cm | masina=");
    Serial.print(masinaLaIesire ? "DA" : "NU");
    Serial.print(" | plata=");
    Serial.println(iesireAprobataDinPython ? "DA" : "NU");
  }

  if (locuriLibere != locuriLibereAnterior)
  {
    locuriLibereAnterior = locuriLibere;

    if (!mesajTemporarActiv)
    {
      afiseazaStareaParcarii();
    }
  }
}

void citesteRaspunsulDeLaPi()
{
  while (Serial.available() > 0)
  {
    char comanda = Serial.read();

    if (comanda == '\n' || comanda == '\r')
    {
      continue;
    }

    if (DEBUG_SERIAL)
    {
      Serial.print("Am primit de la Raspberry: ");
      Serial.println(comanda);
    }

    // ---------------- COMANDA PENTRU IESIRE ----------------
    if (comanda == 'I')
    {
      iesireAprobataDinPython = true;
      mesajPlataIesireAfisat = false;
      timpAprobareIesire = millis();

      afiseazaMesaj("Plata confirmata", "Iesire aprobata", "Apropiati masina", "de senzor", 4000);

      debugPrint("IESIRE APROBATA. Astept masina la senzor.");
      return;
    }

    // ---------------- COMENZI PENTRU INTRARE ----------------
    if (stareIntrare != ASTEAPTA_VALIDARE)
    {
      continue;
    }

    if (comanda == 'A')
    {
      servoIntrare.write(INTRARE_DESCHISA);

      stareIntrare = BARIERA_INTRARE_DESCHISA;
      timpStareIntrare = millis();
      timpFaraMasinaIntrare = 0;

      afiseazaMesaj("Acces permis", "Bariera deschisa", "Puteti intra", "Drum bun!", 3000);
    }
    else if (comanda == 'R')
    {
      servoIntrare.write(INTRARE_INCHISA);

      stareIntrare = INTRARE_GATA;
      timpFaraMasinaIntrare = 0;

      afiseazaMesaj("Acces interzis", "Numar neacceptat", "Bariera inchisa", "", 3000);
    }
  }
}

void proceseazaIntrarea()
{
  unsigned long acum = millis();

  if (stareIntrare == INTRARE_GATA)
  {
    if (masinaLaIntrare && !masinaLaIntrareAnterior)
    {
      if (locuriLibere == 0)
      {
        afiseazaMesaj("PARCARE PLINA", "Nu sunt locuri", "Bariera inchisa", "", 3000);
      }
      else
      {
        Serial.write('C');
        Serial.write('\n');

        stareIntrare = ASTEAPTA_VALIDARE;
        timpStareIntrare = acum;

        afiseazaMesaj("Se verifica...", "Nr. inmatriculare", "Va rugam asteptati", "", TIMP_MAXIM_VALIDARE);

        debugPrint("Am trimis C catre Raspberry.");
      }
    }
  }
  else if (stareIntrare == ASTEAPTA_VALIDARE)
  {
    if (acum - timpStareIntrare >= TIMP_MAXIM_VALIDARE)
    {
      stareIntrare = INTRARE_GATA;
      servoIntrare.write(INTRARE_INCHISA);
      timpFaraMasinaIntrare = 0;

      afiseazaMesaj("Eroare validare", "Fara raspuns Pi", "Bariera inchisa", "", 3000);
    }
  }
  else if (stareIntrare == BARIERA_INTRARE_DESCHISA)
  {
    if (masinaLaIntrare)
    {
      timpFaraMasinaIntrare = 0;
    }
    else
    {
      if (timpFaraMasinaIntrare == 0)
      {
        timpFaraMasinaIntrare = acum;
      }

      if (acum - timpFaraMasinaIntrare >= TIMP_FARA_MASINA_INTRARE)
      {
        servoIntrare.write(INTRARE_INCHISA);

        stareIntrare = INTRARE_GATA;
        timpFaraMasinaIntrare = 0;

        afiseazaMesaj("Va multumim!", "Bariera se inchide", "Parcare placuta", "", 2500);
      }
    }
  }

  masinaLaIntrareAnterior = masinaLaIntrare;
}

void proceseazaIesirea()
{
  unsigned long acum = millis();

  // Daca a venit I, dar masina nu ajunge la iesire in 60 secunde,
  // aprobarea expira.
  if (stareIesire == IESIRE_INCHISA && iesireAprobataDinPython)
  {
    if (!masinaLaIesire && acum - timpAprobareIesire >= TIMP_MAXIM_IESIRE_DUPA_PLATA)
    {
      iesireAprobataDinPython = false;
      mesajPlataIesireAfisat = false;
      timpAprobareIesire = 0;

      servoIesire.write(IESIRE_STOP);

      afiseazaMesaj("Timp expirat", "Apasati PAY", "inca o data", "", 3000);

      debugPrint("A expirat aprobarea de iesire.");
    }
  }

  if (stareIesire == IESIRE_INCHISA)
  {
    // Masina la iesire, dar fara plata.
    if (masinaLaIesire && !iesireAprobataDinPython)
    {
      if (!mesajPlataIesireAfisat)
      {
        afiseazaMesaj("Iesire blocata", "Cautati nr.", "in app si", "apasati PAY", 4000);
        mesajPlataIesireAfisat = true;

        debugPrint("Masina la iesire, dar nu exista plata.");
      }

      return;
    }

    // Masina la iesire si plata confirmata.
    if (masinaLaIesire && iesireAprobataDinPython)
    {
      servoIesire.write(IESIRE_DESCHIDE);

      stareIesire = IESIRE_DESCHISA_5_SECUNDE;
      timpStareIesire = acum;

      afiseazaMesaj("Iesire permisa", "Bariera deschisa", "5 secunde", "Drum bun!", 3000);

      debugPrint("Servo iesire = 180 pentru 5 secunde.");
    }
  }
  else if (stareIesire == IESIRE_DESCHISA_5_SECUNDE)
  {
    if (acum - timpStareIesire >= TIMP_DESCHIDERE_IESIRE)
    {
      servoIesire.write(IESIRE_STOP);

      stareIesire = IESIRE_INCHISA;

      iesireAprobataDinPython = false;
      mesajPlataIesireAfisat = false;
      timpAprobareIesire = 0;

      afiseazaMesaj("Iesire finalizata", "Servo oprit", "Va multumim!", "", 2500);

      debugPrint("Servo iesire = STOP 90. Aprobarea a fost resetata.");
    }
  }
}

void actualizeazaEcranul()
{
  if (mesajTemporarActiv && millis() - inceputMesaj >= durataMesaj)
  {
    mesajTemporarActiv = false;
    afiseazaStareaParcarii();
  }
}

void setup()
{
  Serial.begin(9600);

  pinMode(TRIG_INTRARE, OUTPUT);
  pinMode(ECHO_INTRARE, INPUT);

  pinMode(TRIG_LOC_1, OUTPUT);
  pinMode(ECHO_LOC_1, INPUT);

  pinMode(TRIG_LOC_2, OUTPUT);
  pinMode(ECHO_LOC_2, INPUT);

  pinMode(TRIG_IESIRE, OUTPUT);
  pinMode(ECHO_IESIRE, INPUT);

  servoIntrare.attach(PIN_SERVO_INTRARE);
  servoIesire.attach(PIN_SERVO_IESIRE);

  servoIntrare.write(INTRARE_INCHISA);
  servoIesire.write(IESIRE_STOP);

  lcd.begin();
  lcd.backlight();

  delay(300);

  afiseazaMesaj("Sistem pornit", "Intrare + Iesire", "Servo iesire D10", "Senzor D11/D12", 3000);

  debugPrint("Sistem pornit.");
  debugPrint("TRIG iesire = D11, ECHO iesire = D12.");
  debugPrint("Servo iesire = D10.");
}

void loop()
{
  unsigned long acum = millis();

  if (acum - ultimaCitireSenzori >= INTERVAL_SENZORI)
  {
    ultimaCitireSenzori = acum;
    actualizeazaSenzorii();
  }

  citesteRaspunsulDeLaPi();
  proceseazaIntrarea();
  proceseazaIesirea();
  actualizeazaEcranul();
}
