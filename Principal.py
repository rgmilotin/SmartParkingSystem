import time
import re
import traceback
from pathlib import Path

import cv2
import pymysql
import pytesseract
import serial


try:
    from picamera2 import Picamera2
except Exception:
    Picamera2 = None


# ===================== CONFIGURARE =====================

PORT_ARDUINO = "/dev/ttyUSB0"   
BAUD_RATE = 9600

DB_HOST = "localhost"
DB_USER = "parcare_user"
DB_PASSWORD = "parcare123"
DB_NAME = "parcare_rb"

CALE_POZA = Path("poza_intrare.jpg")
DEBUG_DIR = Path("debug_ocr")
DEBUG_DIR.mkdir(exist_ok=True)

PRET_PE_MINUT = 0.5

PRAG_CROP_START = 0.35
PRAG_CROP_STOP = 0.95

MAX_DREPTUNGHIURI = 10


# ===================== JUDETE / CORECTARE OCR =====================

JUDETE_RO = {
    "AB", "AR", "AG", "BC", "BH", "BN", "BR", "BT", "BV", "BZ",
    "CS", "CL", "CJ", "CT", "CV", "DB", "DJ", "GL", "GR", "GJ",
    "HR", "HD", "IL", "IS", "IF", "MM", "MH", "MS", "NT", "OT",
    "PH", "SM", "SJ", "SB", "SV", "TR", "TM", "TL", "VS", "VL",
    "VN", "B"
}

PREFIXE_GRATUITE = ("MAI", "CD", "TC", "CO")

OCR_TO_DIGIT = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "A": "4",
    "S": "5",
    "G": "6",
    "B": "8",
    "T": "7"
}

OCR_TO_LETTER = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "4": "A",
    "5": "S",
    "6": "G",
    "8": "B",
    "7": "T"
}


# ===================== BAZA DE DATE =====================

def conectare_baza_date():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        cursorclass=pymysql.cursors.DictCursor
    )


def creeaza_tabele_daca_nu_exista():
    db = conectare_baza_date()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS clienti (
                    id_client INT AUTO_INCREMENT PRIMARY KEY,
                    nr_inmatriculare VARCHAR(20) NOT NULL UNIQUE,
                    cnp VARCHAR(20) NULL,
                    nume VARCHAR(100) NULL,
                    prenume VARCHAR(100) NULL,
                    firma VARCHAR(100) NULL,
                    este_angajat TINYINT(1) NOT NULL DEFAULT 0
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS log_parcare (
                    id_log INT AUTO_INCREMENT PRIMARY KEY,
                    nr_inmatriculare VARCHAR(20) NOT NULL,
                    timpul_venirii DATETIME NOT NULL,
                    timpul_plecarii DATETIME NULL,
                    durata_minute INT NULL,
                    trebuie_sa_plateasca TINYINT(1) NOT NULL DEFAULT 1,
                    suma_de_plata DECIMAL(10,2) NOT NULL DEFAULT 0.00,
                    a_platit TINYINT(1) NOT NULL DEFAULT 0,
                    comanda_iesire_trimisa TINYINT(1) NOT NULL DEFAULT 0
                )
                """
            )

            # Pentru cazul in care tabelul exista deja, dar lipsesc coloane.
            alteruri = [
                "ALTER TABLE log_parcare ADD COLUMN IF NOT EXISTS durata_minute INT NULL",
                "ALTER TABLE log_parcare ADD COLUMN IF NOT EXISTS trebuie_sa_plateasca TINYINT(1) NOT NULL DEFAULT 1",
                "ALTER TABLE log_parcare ADD COLUMN IF NOT EXISTS suma_de_plata DECIMAL(10,2) NOT NULL DEFAULT 0.00",
                "ALTER TABLE log_parcare ADD COLUMN IF NOT EXISTS a_platit TINYINT(1) NOT NULL DEFAULT 0",
                "ALTER TABLE log_parcare ADD COLUMN IF NOT EXISTS comanda_iesire_trimisa TINYINT(1) NOT NULL DEFAULT 0",
                "ALTER TABLE clienti ADD COLUMN IF NOT EXISTS este_angajat TINYINT(1) NOT NULL DEFAULT 0"
            ]

            for sql in alteruri:
                try:
                    cursor.execute(sql)
                except Exception:
                    pass

        db.commit()

    finally:
        db.close()


def cauta_log_deschis(cursor, nr_inmatriculare):
    cursor.execute(
        """
        SELECT id_log
        FROM log_parcare
        WHERE nr_inmatriculare = %s
          AND timpul_plecarii IS NULL
        ORDER BY timpul_venirii DESC
        LIMIT 1
        """,
        (nr_inmatriculare,)
    )

    rezultat = cursor.fetchone()

    if rezultat is None:
        return None

    return rezultat["id_log"]


def este_angajat(cursor, nr_inmatriculare):
    cursor.execute(
        """
        SELECT este_angajat
        FROM clienti
        WHERE nr_inmatriculare = %s
        LIMIT 1
        """,
        (nr_inmatriculare,)
    )

    rezultat = cursor.fetchone()

    if rezultat is None:
        return False

    return int(rezultat["este_angajat"]) == 1


def este_numar_gratuit(nr_inmatriculare):
    return nr_inmatriculare.startswith(PREFIXE_GRATUITE)


def adauga_client_necunoscut(cursor, nr_inmatriculare):
    cursor.execute(
        """
        INSERT IGNORE INTO clienti
        (nr_inmatriculare, cnp, nume, prenume, firma, este_angajat)
        VALUES (%s, NULL, NULL, NULL, NULL, 0)
        """,
        (nr_inmatriculare,)
    )


def proceseaza_intrare_camera(nr_inmatriculare):
    db = conectare_baza_date()

    try:
        with db.cursor() as cursor:
            id_log_deschis = cauta_log_deschis(cursor, nr_inmatriculare)

            if id_log_deschis is not None:
                print(
                    f"Numarul {nr_inmatriculare} este deja in parcare. Nu creez log nou.",
                    flush=True
                )
                return False

            angajat = este_angajat(cursor, nr_inmatriculare)
            gratuit = este_numar_gratuit(nr_inmatriculare)

            if not angajat and not gratuit:
                adauga_client_necunoscut(cursor, nr_inmatriculare)

            if angajat or gratuit:
                trebuie_sa_plateasca = 0
                a_platit = 0
            else:
                trebuie_sa_plateasca = 1
                a_platit = 0

            cursor.execute(
                """
                INSERT INTO log_parcare
                (
                    nr_inmatriculare,
                    timpul_venirii,
                    timpul_plecarii,
                    durata_minute,
                    trebuie_sa_plateasca,
                    suma_de_plata,
                    a_platit,
                    comanda_iesire_trimisa
                )
                VALUES (%s, NOW(), NULL, NULL, %s, 0.00, %s, 0)
                """,
                (nr_inmatriculare, trebuie_sa_plateasca, a_platit)
            )

        db.commit()

        if gratuit:
            print(f"A intrat nr: {nr_inmatriculare}. Numar special/gratuit.", flush=True)
        elif angajat:
            print(f"A intrat nr: {nr_inmatriculare}. Este angajat.", flush=True)
        else:
            print(f"A intrat nr: {nr_inmatriculare}. Vizitator/neangajat.", flush=True)

        return True

    finally:
        db.close()


def verifica_iesiri_platite_si_trimite_la_arduino(arduino):
    db = conectare_baza_date()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT id_log, nr_inmatriculare
                FROM log_parcare
                WHERE a_platit = 1
                  AND timpul_plecarii IS NOT NULL
                  AND comanda_iesire_trimisa = 0
                ORDER BY timpul_plecarii ASC
                LIMIT 1
                """
            )

            rezultat = cursor.fetchone()

            if rezultat is None:
                return

            id_log = rezultat["id_log"]
            nr_inmatriculare = rezultat["nr_inmatriculare"]

            arduino.write(b"I\n")
            arduino.flush()

            print(
                f"Am trimis catre Arduino: I pentru iesirea nr {nr_inmatriculare}",
                flush=True
            )

            cursor.execute(
                """
                UPDATE log_parcare
                SET comanda_iesire_trimisa = 1
                WHERE id_log = %s
                """,
                (id_log,)
            )

        db.commit()

    except Exception as e:
        print("Eroare la verificarea iesirilor platite:", e, flush=True)

    finally:
        db.close()


# ===================== CORECTARE NUMAR OCR =====================

def normalizeaza_text_ocr(text):
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def corecteaza_litere_strict(text):
    rezultat = ""

    for ch in text:
        if "A" <= ch <= "Z":
            rezultat += ch
        elif ch in OCR_TO_LETTER:
            rezultat += OCR_TO_LETTER[ch]
        else:
            return None

    return rezultat


def corecteaza_cifre_strict(text):
    rezultat = ""

    for ch in text:
        if ch.isdigit():
            rezultat += ch
        elif ch in OCR_TO_DIGIT:
            rezultat += OCR_TO_DIGIT[ch]
        else:
            return None

    return rezultat


def incearca_corectare_special(text):
    for prefix in PREFIXE_GRATUITE:
        if text.startswith(prefix):
            rest = text[len(prefix):]

            if rest == "":
                return prefix

            cifre = corecteaza_cifre_strict(rest)

            if cifre is not None and 1 <= len(cifre) <= 6:
                return prefix + cifre

    return None


def incearca_corectare_rosu(text):
    for lungime_judet in [2, 1]:
        if len(text) <= lungime_judet:
            continue

        judet_raw = text[:lungime_judet]
        cifre_raw = text[lungime_judet:]

        judet = corecteaza_litere_strict(judet_raw)
        cifre = corecteaza_cifre_strict(cifre_raw)

        if judet in JUDETE_RO and cifre is not None and 3 <= len(cifre) <= 6:
            return judet + cifre

    return None


def incearca_corectare_standard(text):
    for lungime_judet in [2, 1]:
        if len(text) < lungime_judet + 5:
            continue

        judet_raw = text[:lungime_judet]
        judet = corecteaza_litere_strict(judet_raw)

        if judet not in JUDETE_RO:
            continue

        lungimi_cifre = [2]

        if judet == "B":
            lungimi_cifre = [3, 2]

        for lungime_cifre in lungimi_cifre:
            start_cifre = lungime_judet
            stop_cifre = start_cifre + lungime_cifre

            start_litere = stop_cifre
            stop_litere = start_litere + 3

            if len(text) < stop_litere:
                continue

            cifre_raw = text[start_cifre:stop_cifre]
            litere_raw = text[start_litere:stop_litere]

            cifre = corecteaza_cifre_strict(cifre_raw)
            litere = corecteaza_litere_strict(litere_raw)

            if cifre is not None and litere is not None:
                if len(cifre) == lungime_cifre and len(litere) == 3:
                    return judet + cifre + litere

    return None


def curata_numar(text):
    text = normalizeaza_text_ocr(text)

    if text == "":
        return None

    print(f"Text OCR curatat initial: {text}", flush=True)

    special = incearca_corectare_special(text)
    if special:
        return special

    rosu = incearca_corectare_rosu(text)
    if rosu:
        return rosu

    standard = incearca_corectare_standard(text)
    if standard:
        return standard

    return None


# ===================== CAMERA =====================

def initializeaza_camera():
    if Picamera2 is not None:
        camera = Picamera2()
        config = camera.create_still_configuration(
            main={"size": (1920, 1080)}
        )
        camera.configure(config)
        camera.start()
        time.sleep(2)
        print("Camera Picamera2 pornita.", flush=True)
        return ("picamera2", camera)

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        raise RuntimeError("Nu pot deschide camera cu OpenCV.")

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    print("Camera OpenCV pornita.", flush=True)
    return ("opencv", camera)


def captureaza_poza(camera_obj, cale_poza):
    tip_camera, camera = camera_obj

    if tip_camera == "picamera2":
        camera.capture_file(str(cale_poza))
        return True

    ret, frame = camera.read()

    if not ret:
        return False

    cv2.imwrite(str(cale_poza), frame)
    return True


# ===================== OCR IMAGINE =====================

def ocr_pe_roi(roi, nume_debug):
    if roi is None or roi.size == 0:
        return None

    gri = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    gri = cv2.resize(
        gri,
        None,
        fx=3,
        fy=3,
        interpolation=cv2.INTER_CUBIC
    )

    gri = cv2.GaussianBlur(gri, (3, 3), 0)

    _, binara = cv2.threshold(
        gri,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    cale_binara = DEBUG_DIR / f"placuta_binara_{nume_debug}.jpg"
    cv2.imwrite(str(cale_binara), binara)

    config = (
        "--oem 3 --psm 7 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )

    texte_de_incercat = []

    try:
        text1 = pytesseract.image_to_string(binara, config=config)
        texte_de_incercat.append(text1)
    except Exception as e:
        print("Eroare Tesseract varianta normala:", e, flush=True)

    try:
        inversata = cv2.bitwise_not(binara)
        text2 = pytesseract.image_to_string(inversata, config=config)
        texte_de_incercat.append(text2)
    except Exception as e:
        print("Eroare Tesseract varianta inversata:", e, flush=True)

    for text in texte_de_incercat:
        print(f"OCR raw [{nume_debug}]: {repr(text)}", flush=True)

        rezultat = curata_numar(text)

        if rezultat:
            print(f"Numar gasit [{nume_debug}]: {rezultat}", flush=True)
            return rezultat

    return None


def citeste_numar_inmatriculare(cale_poza):
    img = cv2.imread(str(cale_poza))

    if img is None:
        print("Nu am putut citi poza.", flush=True)
        return None

    img = cv2.rotate(img, cv2.ROTATE_180)
    cv2.imwrite(str(DEBUG_DIR / "01_poza_intoarsa.jpg"), img)

    inaltime, latime = img.shape[:2]

    start_crop = int(inaltime * PRAG_CROP_START)
    stop_crop = int(inaltime * PRAG_CROP_STOP)

    img_crop = img[start_crop:stop_crop, 0:latime]
    cv2.imwrite(str(DEBUG_DIR / "02_poza_crop_numar.jpg"), img_crop)

    gri = cv2.cvtColor(img_crop, cv2.COLOR_BGR2GRAY)
    gri = cv2.bilateralFilter(gri, 11, 17, 17)

    margini = cv2.Canny(gri, 30, 200)
    cv2.imwrite(str(DEBUG_DIR / "03_margini_canny.jpg"), margini)

    contururi, _ = cv2.findContours(
        margini.copy(),
        cv2.RETR_TREE,
        cv2.CHAIN_APPROX_SIMPLE
    )

    contururi = sorted(contururi, key=cv2.contourArea, reverse=True)[:80]

    dreptunghiuri = []

    for contur in contururi:
        x, y, w, h = cv2.boundingRect(contur)

        if h == 0:
            continue

        raport = w / float(h)
        aria = w * h

        if aria < 1000:
            continue

        if 1.5 <= raport <= 8.5:
            dreptunghiuri.append((x, y, w, h))

    dreptunghiuri = sorted(
        dreptunghiuri,
        key=lambda r: r[2] * r[3],
        reverse=True
    )[:MAX_DREPTUNGHIURI]

    img_debug = img_crop.copy()

    for i, (x, y, w, h) in enumerate(dreptunghiuri, start=1):
        cv2.rectangle(img_debug, (x, y), (x + w, y + h), (0, 255, 0), 3)

    cv2.imwrite(str(DEBUG_DIR / "04_dreptunghiuri_gasite.jpg"), img_debug)

    for i, (x, y, w, h) in enumerate(dreptunghiuri, start=1):
        pad_x = int(w * 0.10)
        pad_y = int(h * 0.25)

        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(img_crop.shape[1], x + w + pad_x)
        y2 = min(img_crop.shape[0], y + h + pad_y)

        roi = img_crop[y1:y2, x1:x2]

        cv2.imwrite(str(DEBUG_DIR / f"crop_dreptunghi_{i}.jpg"), roi)

        rezultat = ocr_pe_roi(roi, str(i))

        if rezultat:
            return rezultat

    print("Nu am gasit numar in dreptunghiuri. Incerc OCR pe crop mare.", flush=True)

    rezultat_crop_mare = ocr_pe_roi(img_crop, "crop_mare")

    if rezultat_crop_mare:
        return rezultat_crop_mare

    return None


# ===================== MAIN LOOP =====================

def main():
    creeaza_tabele_daca_nu_exista()

    print("Deschid conexiunea seriala cu Arduino...", flush=True)
    arduino = serial.Serial(PORT_ARDUINO, BAUD_RATE, timeout=0.2)
    time.sleep(2)

    print("Conexiune seriala deschisa.", flush=True)

    camera = initializeaza_camera()

    print("Sistem pornit. Astept comenzi de la Arduino...", flush=True)

    while True:
        try:
            verifica_iesiri_platite_si_trimite_la_arduino(arduino)

            linie = arduino.readline().decode("utf-8", errors="ignore").strip()

            if linie == "":
                time.sleep(0.1)
                continue

            print(f"Arduino -> Raspberry: {linie}", flush=True)

            if linie == "C":
                print("Masina detectata la intrare. Fac poza...", flush=True)

                poza_ok = captureaza_poza(camera, CALE_POZA)

                if not poza_ok:
                    print("Nu am putut face poza.", flush=True)
                    arduino.write(b"R\n")
                    arduino.flush()
                    continue

                numar_inmatriculare = citeste_numar_inmatriculare(CALE_POZA)

                if numar_inmatriculare:
                    print(
                        f"Numar final recunoscut: {numar_inmatriculare}",
                        flush=True
                    )

                    acces_permis = proceseaza_intrare_camera(numar_inmatriculare)

                    if acces_permis:
                        arduino.write(b"A\n")
                        arduino.flush()
                        print("Am trimis A catre Arduino.", flush=True)
                    else:
                        arduino.write(b"R\n")
                        arduino.flush()
                        print("Am trimis R catre Arduino: log deja activ.", flush=True)

                else:
                    print("Nu am gasit numar de inmatriculare.", flush=True)
                    arduino.write(b"R\n")
                    arduino.flush()
                    print("Am trimis R catre Arduino.", flush=True)

            time.sleep(0.1)

        except KeyboardInterrupt:
            print("Oprire manuala.", flush=True)
            break

        except Exception as e:
            print("Eroare in bucla principala:", e, flush=True)
            traceback.print_exc()
            time.sleep(1)


if __name__ == "__main__":
    main()