from flask import Flask, request, render_template_string
import pymysql
import re


app = Flask(__name__)

DB_HOST = "localhost"
DB_USER = "parcare_user"
DB_PASSWORD = "parcare123"
DB_NAME = "parcare_rb"

PRET_PE_MINUT = 0.5


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


def normalizeaza_numar(text):
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text


def cauta_log_activ(nr_inmatriculare):
    db = conectare_baza_date()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    l.id_log,
                    l.nr_inmatriculare,
                    l.timpul_venirii,
                    l.timpul_plecarii,
                    l.trebuie_sa_plateasca,
                    l.suma_de_plata,
                    l.a_platit,
                    c.nume,
                    c.prenume,
                    c.cnp,
                    c.firma,
                    c.este_angajat,
                    GREATEST(
                        1,
                        CEIL(TIMESTAMPDIFF(SECOND, l.timpul_venirii, NOW()) / 60)
                    ) AS durata_curenta,
                    CASE
                        WHEN l.trebuie_sa_plateasca = 0 THEN 0.00
                        ELSE GREATEST(
                            1,
                            CEIL(TIMESTAMPDIFF(SECOND, l.timpul_venirii, NOW()) / 60)
                        ) * %s
                    END AS suma_curenta
                FROM log_parcare l
                LEFT JOIN clienti c
                    ON l.nr_inmatriculare = c.nr_inmatriculare
                WHERE l.nr_inmatriculare = %s
                  AND l.timpul_plecarii IS NULL
                  AND l.a_platit = 0
                ORDER BY l.timpul_venirii DESC
                LIMIT 1
                """,
                (PRET_PE_MINUT, nr_inmatriculare)
            )

            return cursor.fetchone()

    finally:
        db.close()


def marcheaza_platit(id_log):
    db = conectare_baza_date()

    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT trebuie_sa_plateasca
                FROM log_parcare
                WHERE id_log = %s
                """,
                (id_log,)
            )

            rezultat = cursor.fetchone()

            if rezultat is None:
                return False

            trebuie_sa_plateasca = int(rezultat["trebuie_sa_plateasca"])

            if trebuie_sa_plateasca == 0:
                cursor.execute(
                    """
                    UPDATE log_parcare
                    SET timpul_plecarii = NOW(),
                        durata_minute = GREATEST(
                            1,
                            CEIL(TIMESTAMPDIFF(SECOND, timpul_venirii, NOW()) / 60)
                        ),
                        suma_de_plata = 0.00,
                        a_platit = 1,
                        comanda_iesire_trimisa = 0
                    WHERE id_log = %s
                    """,
                    (id_log,)
                )
            else:
                cursor.execute(
                    """
                    UPDATE log_parcare
                    SET timpul_plecarii = NOW(),
                        durata_minute = GREATEST(
                            1,
                            CEIL(TIMESTAMPDIFF(SECOND, timpul_venirii, NOW()) / 60)
                        ),
                        suma_de_plata = GREATEST(
                            1,
                            CEIL(TIMESTAMPDIFF(SECOND, timpul_venirii, NOW()) / 60)
                        ) * %s,
                        a_platit = 1,
                        comanda_iesire_trimisa = 0
                    WHERE id_log = %s
                    """,
                    (PRET_PE_MINUT, id_log)
                )

        db.commit()
        return True

    finally:
        db.close()


HTML = """
<!DOCTYPE html>
<html lang="ro">
<head>
    <meta charset="UTF-8">
    <title>Parcare</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f2f2f2;
            padding: 40px;
        }

        .container {
            max-width: 650px;
            margin: auto;
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 0 12px rgba(0,0,0,0.15);
        }

        h1 {
            text-align: center;
        }

        input {
            width: 100%;
            padding: 14px;
            font-size: 20px;
            margin-top: 10px;
            box-sizing: border-box;
            text-transform: uppercase;
        }

        button {
            width: 100%;
            padding: 14px;
            font-size: 18px;
            margin-top: 15px;
            cursor: pointer;
            border: none;
            border-radius: 8px;
        }

        .search-btn {
            background: #333;
            color: white;
        }

        .pay-btn {
            background: #1b8f3a;
            color: white;
        }

        .card {
            background: #f7f7f7;
            padding: 15px;
            margin-top: 20px;
            border-radius: 8px;
        }

        .success {
            background: #d9fdd3;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            font-weight: bold;
        }

        .error {
            background: #ffd4d4;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            font-weight: bold;
        }

        .big-price {
            font-size: 30px;
            font-weight: bold;
            color: #1b8f3a;
        }

        .small-info {
            font-size: 14px;
            color: #555;
            margin-top: 8px;
        }
    </style>
</head>

<body>
    <div class="container">
        <h1>Parcare</h1>

        <form method="POST" action="/">
            <label>Numar de inmatriculare:</label>
            <input type="text" name="nr_inmatriculare" placeholder="Ex: TM13RFI" required>
            <button class="search-btn" type="submit">Search</button>
        </form>

        {% if mesaj %}
            <div class="{{ tip_mesaj }}">
                {{ mesaj }}
            </div>
        {% endif %}

        {% if log %}
            <div class="card">
                <h2>Rezultat pentru {{ log.nr_inmatriculare }}</h2>

                <p><b>Ora intrarii:</b> {{ log.timpul_venirii }}</p>

                {% if log.nume %}
                    <p><b>Client:</b> {{ log.nume }} {{ log.prenume }}</p>
                    <p><b>Firma:</b> {{ log.firma }}</p>
                {% else %}
                    <p><b>Client:</b> necunoscut</p>
                {% endif %}

                {% if log.trebuie_sa_plateasca == 0 %}
                    <p><b>Status:</b> angajat / numar special / acces gratuit</p>
                    <p><b>Durata:</b> {{ log.durata_curenta }} minute</p>
                    <p>Are de plata:</p>
                    <p class="big-price">0.00 lei</p>

                    <form method="POST" action="/pay">
                        <input type="hidden" name="id_log" value="{{ log.id_log }}">
                        <button class="pay-btn" type="submit">PAY 0 lei / Iesire</button>
                    </form>

                    <p class="small-info">
                        Dupa apasare, aplicatia salveaza iesirea, iar codul principal trimite comanda catre Arduino.
                    </p>
                {% else %}
                    <p><b>Status:</b> vizitator / neangajat</p>
                    <p><b>Durata:</b> {{ log.durata_curenta }} minute</p>
                    <p><b>Tarif:</b> 0.5 lei / minut</p>
                    <p>Are de plata:</p>
                    <p class="big-price">{{ "%.2f"|format(log.suma_curenta) }} lei</p>

                    <form method="POST" action="/pay">
                        <input type="hidden" name="id_log" value="{{ log.id_log }}">
                        <button class="pay-btn" type="submit">PAY</button>
                    </form>

                    <p class="small-info">
                        Dupa plata, aplicatia salveaza iesirea, iar codul principal trimite comanda catre Arduino.
                    </p>
                {% endif %}
            </div>
        {% endif %}
    </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def index():
    mesaj = None
    tip_mesaj = None
    log = None

    if request.method == "POST":
        nr_inmatriculare = request.form.get("nr_inmatriculare", "")
        nr_inmatriculare = normalizeaza_numar(nr_inmatriculare)

        if nr_inmatriculare == "":
            mesaj = "Introdu un numar de inmatriculare."
            tip_mesaj = "error"
        else:
            log = cauta_log_activ(nr_inmatriculare)

            if log is None:
                mesaj = f"Nu exista log activ neplatit pentru numarul {nr_inmatriculare}."
                tip_mesaj = "error"

    return render_template_string(
        HTML,
        mesaj=mesaj,
        tip_mesaj=tip_mesaj,
        log=log
    )


@app.route("/pay", methods=["POST"])
def pay():
    id_log = request.form.get("id_log")

    if id_log:
        rezultat = marcheaza_platit(id_log)

        if rezultat:
            mesaj = "Plata confirmata. Cererea de iesire a fost salvata. Mergeti la bariera."
            tip_mesaj = "success"
        else:
            mesaj = "Nu am gasit logul pentru aceasta plata."
            tip_mesaj = "error"
    else:
        mesaj = "Eroare: lipsa id_log."
        tip_mesaj = "error"

    return render_template_string(
        HTML,
        mesaj=mesaj,
        tip_mesaj=tip_mesaj,
        log=None
    )


if __name__ == "__main__":
    creeaza_tabele_daca_nu_exista()
    app.run(host="0.0.0.0", port=5000, debug=False)