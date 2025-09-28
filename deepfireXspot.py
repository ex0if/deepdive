import csv
import requests
import time
from bs4 import BeautifulSoup
from urllib.parse import quote
from datetime import datetime
import os
from collections import defaultdict
import re
import hashlib
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- Firebase Initialisierung nur über GitHub Secret ---
try:
    if "FIRESTORE_KEY" in os.environ:
        # Secret aus GitHub Actions (als JSON-String)
        key_dict = json.loads(os.environ["FIRESTORE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        print("Firebase erfolgreich initialisiert.")
    else:
        raise RuntimeError("Umgebungsvariable FIRESTORE_KEY nicht gesetzt!")

except Exception as e:
    print("Fehler bei der Initialisierung von Firebase:", e)
    db = None

# --- Report-Variablen initialisieren ---
start_time = datetime.now()
request_count = 0
successful_requests = 0
errors_list = []
timeouts_count = 0
request_exceptions_count = 0
general_exceptions_count = 0
prices_found_total = 0
entries_skipped = 0
spot_prices_scraped = 0


def add_error_to_report(error_type, message, entry_info=""):
    """Fügt einen Fehler zum Report hinzu"""
    global errors_list
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errors_list.append({
        "timestamp": timestamp,
        "type": error_type,
        "message": str(message),
        "entry": entry_info
    })


def create_report(report_filename="scraping_report.txt"):
    end_time = datetime.now()
    total_duration = end_time - start_time

    report_content = f"""
=== SCRAPING REPORT ===
Datum: {end_time.strftime("%Y-%m-%d %H:%M:%S")}

=== ZEITSTATISTIKEN ===
Startzeit: {start_time.strftime("%Y-%m-%d %H:%M:%S")}
Endzeit: {end_time.strftime("%Y-%m-%d %H:%M:%S")}
Gesamtdauer: {total_duration}
Gesamtdauer (Sekunden): {total_duration.total_seconds():.2f}

=== ANFRAGE-STATISTIKEN ===
Gesamte Anfragen: {request_count}
Erfolgreiche Anfragen: {successful_requests}
Gefundene Preise gesamt: {prices_found_total}
Spot-Preise gescrapt: {spot_prices_scraped}
Übersprungene Einträge: {entries_skipped}

=== FEHLER-STATISTIKEN ===
Timeout-Fehler: {timeouts_count}
Request-Exceptions: {request_exceptions_count}
Allgemeine Exceptions: {general_exceptions_count}
Gesamte Fehler: {len(errors_list)}

=== ERFOLGSQUOTE ===
Erfolgsquote Anfragen: {(successful_requests / request_count * 100 if request_count > 0 else 0):.2f}%
Durchschnittliche Preise pro Anfrage: {(prices_found_total / successful_requests if successful_requests > 0 else 0):.2f}

=== DETAILLIERTE FEHLERLISTE ===
"""

    if errors_list:
        for i, error in enumerate(errors_list, 1):
            report_content += f"{i}. [{error['timestamp']}] {error['type']}: {error['message']}"
            if error['entry']:
                report_content += f" | Eintrag: {error['entry']}"
            report_content += "\n"
    else:
        report_content += "Keine Fehler aufgetreten.\n"

    report_content += f"\n=== ENDE REPORT ===\n"

    # Report in Datei schreiben
    try:
        with open(report_filename, "w", encoding="utf-8") as f:
            f.write(report_content)
        print(f"\nReport erstellt: {report_filename}")
    except Exception as e:
        print(f"Fehler beim Erstellen des Reports: {e}")

    # Report auch in Konsole ausgeben (gekürzte Version)
    print(f"\n=== SCRAPING ABGESCHLOSSEN ===")
    print(f"Gesamtdauer: {total_duration}")
    print(f"Anfragen: {request_count} | Erfolgreich: {successful_requests}")
    print(f"Gefundene Preise: {prices_found_total}")
    print(f"Spot-Preise: {spot_prices_scraped}")
    print(f"Fehler: {len(errors_list)} | Timeouts: {timeouts_count}")
    print(f"Erfolgsquote: {(successful_requests / request_count * 100 if request_count > 0 else 0):.2f}%")


def sanitize_document_id(text):
    """Sanitize für Firestore-IDs"""
    if not text:
        return "unknown"
    sanitized = re.sub(r'[/\s\-\.\,\(\)\[\]\{\}\<\>\"\'\:\;\?\!\@\#\$\%\^\&\*\+\=\|\\\`\~]', '_', str(text))
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.strip('_')
    if not sanitized:
        sanitized = "unknown"
    elif len(sanitized) > 100:
        sanitized = sanitized[:100]
    return sanitized


def create_coin_key(material, name, stueckelung, jahrgang):
    """Create a properly formatted key for coin data"""
    return f"{sanitize_document_id(material)}_{sanitize_document_id(name)}_{sanitize_document_id(stueckelung)}_{sanitize_document_id(jahrgang)}"


def scrape_gold_spot_prices():
    """
    Scrapt die aktuellen Gold- und Silberpreise von www.gold.de
    """
    global request_count, successful_requests, spot_prices_scraped
    
    url = "https://www.gold.de"
    
    # Headers setzen um wie ein normaler Browser zu wirken
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        print("Scraping Gold- und Silber-Spot-Preise von www.gold.de...")
        request_count += 1
        
        # Website abrufen
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        successful_requests += 1
        
        # HTML parsen
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Preisdaten extrahieren
        prices = {}
        
        # Gold Preise
        gold_usd = soup.find('td', class_='au_gold_usd_s')
        gold_eur = soup.find('td', class_='au_gold_eur_s')
        gold_eur_gram = soup.find('td', class_='au_gold_eur_per_gram')
        gold_eur_kg = soup.find('td', class_='au_gold_eur_per_kg')
        
        # Silber Preise
        silver_usd = soup.find('td', class_='au_silber_usd_s')
        silver_eur = soup.find('td', class_='au_silber_eur_s')
        silver_eur_gram = soup.find('td', class_='au_silber_eur_per_gram')
        silver_eur_kg = soup.find('td', class_='au_silber_eur_per_kg')
        
        # Hilfsfunktion um Preis und Währung zu extrahieren
        def extract_price_and_unit(element):
            if element:
                text = element.get_text(strip=True)
                # Preis und Einheit trennen
                span = element.find('span')
                if span:
                    unit = span.get_text(strip=True)
                    price_str = text.replace(unit, '').strip()
                    # Preis bereinigen für numerische Verarbeitung
                    try:
                        # Entfernt Punkte (Tausendertrennzeichen) und ersetzt Komma durch Punkt
                        cleaned_price = price_str.replace('.', '').replace(',', '.')
                        price_float = float(cleaned_price)
                        return price_float, unit
                    except ValueError:
                        return price_str, unit
            return None, None
        
        # Gold Preise verarbeiten
        if gold_usd:
            price, unit = extract_price_and_unit(gold_usd)
            if price is not None:
                prices['gold_usd_oz'] = price
                spot_prices_scraped += 1
                
        if gold_eur:
            price, unit = extract_price_and_unit(gold_eur)
            if price is not None:
                prices['gold_eur_oz'] = price
                spot_prices_scraped += 1
                
        if gold_eur_gram:
            price, unit = extract_price_and_unit(gold_eur_gram)
            if price is not None:
                prices['gold_eur_gram'] = price
                spot_prices_scraped += 1
                
        if gold_eur_kg:
            price, unit = extract_price_and_unit(gold_eur_kg)
            if price is not None:
                prices['gold_eur_kg'] = price
                spot_prices_scraped += 1
        
        # Silber Preise verarbeiten
        if silver_usd:
            price, unit = extract_price_and_unit(silver_usd)
            if price is not None:
                prices['silver_usd_oz'] = price
                spot_prices_scraped += 1
                
        if silver_eur:
            price, unit = extract_price_and_unit(silver_eur)
            if price is not None:
                prices['silver_eur_oz'] = price
                spot_prices_scraped += 1
                
        if silver_eur_gram:
            price, unit = extract_price_and_unit(silver_eur_gram)
            if price is not None:
                prices['silver_eur_gram'] = price
                spot_prices_scraped += 1
                
        if silver_eur_kg:
            price, unit = extract_price_and_unit(silver_eur_kg)
            if price is not None:
                prices['silver_eur_kg'] = price
                spot_prices_scraped += 1
        
        return prices
        
    except requests.exceptions.Timeout:
        global timeouts_count
        timeouts_count += 1
        add_error_to_report("TIMEOUT", "Timeout beim Scrapen der Spot-Preise", "gold.de")
        return None
    except requests.exceptions.RequestException as e:
        global request_exceptions_count
        request_exceptions_count += 1
        add_error_to_report("REQUEST_EXCEPTION", f"Fehler beim Abrufen der Spot-Preise: {e}", "gold.de")
        return None
    except Exception as e:
        global general_exceptions_count
        general_exceptions_count += 1
        add_error_to_report("GENERAL_EXCEPTION", f"Fehler beim Parsen der Spot-Preise: {e}", "gold.de")
        return None


def upload_spot_prices_to_firestore(spot_prices):
    """
    Lädt die Spot-Preise in die 'spot' Sammlung mit dem aktuellen Datum als Dokument-ID
    """
    if not spot_prices:
        print("Keine Spot-Preise zum Hochladen.")
        return
        
    try:
        current_date = datetime.now().strftime("%Y-%m-%d")
        iso_timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Spot-Preise mit Timestamp vorbereiten
        spot_data = {
            "timestamp": iso_timestamp,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **spot_prices  # Alle Spot-Preise hinzufügen
        }
        
        # In Firestore hochladen
        spot_collection_ref = db.collection("spot")
        spot_doc_ref = spot_collection_ref.document(current_date)
        
        # Dokument setzen (überschreibt falls bereits vorhanden)
        spot_doc_ref.set(spot_data)
        
        print(f"Spot-Preise erfolgreich in 'spot/{current_date}' hochgeladen.")
        print(f"Hochgeladene Preise: {list(spot_prices.keys())}")
        
    except Exception as e:
        add_error_to_report("SPOT_FIRESTORE_UPLOAD", f"Fehler beim Hochladen der Spot-Preise: {e}")
        print(f"Fehler beim Hochladen der Spot-Preise nach Firestore: {e}")
        raise


# --- Dateipfad-Konfiguration ---
TEMP_DATA_CSV_FILENAME = "scraped_prices_temp.csv"
CSV_HEADERS = ["material", "art", "name", "jahrgang", "stueckelung", "preis", "datum", "haendler", "gramm_preis", "spot_preis"]

BACKUP_FOLDER = "Backup"
if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)
    print(f"Backup-Ordner '{BACKUP_FOLDER}' erstellt.")

TEMP_DATA_CSV_PATH = TEMP_DATA_CSV_FILENAME
if not os.path.exists(TEMP_DATA_CSV_PATH):
    with open(TEMP_DATA_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
    print(f"Temporäre CSV-Datei '{TEMP_DATA_CSV_PATH}' erstellt mit Header.")
else:
    print(f"Temporäre CSV-Datei '{TEMP_DATA_CSV_PATH}' existiert bereits. Neue Daten werden angehängt.")


def upload_to_firestore(coin_data, batch_size=499):
    print("\n--- Starte hierarchischen Upload nach Firestore ---")
    current_date = datetime.now().strftime("%Y-%m-%d")
    collection_ref = db.collection(current_date)
    batch = db.batch()
    doc_count = 0
    uploaded_count = 0

    try:
        for key, data in coin_data.items():
            sanitized_key = sanitize_document_id(key)
            if not sanitized_key or sanitized_key == "unknown":
                hash_suffix = hashlib.md5(key.encode()).hexdigest()[:8]
                sanitized_key = f"coin_{hash_suffix}"

            sorted_prices = sorted(data["prices"], key=lambda x: x["preis"] if x["preis"] is not None else 0, reverse=True)

            parent_doc_ref = collection_ref.document(sanitized_key)
            parent_data = {
                "material": data["material"],
                "name": data["name"],
                "stueckelung": data["stueckelung"],
                "jahrgang": data["jahrgang"],
                "original_key": key
            }
            batch.set(parent_doc_ref, parent_data)
            doc_count += 1
            uploaded_count += 1

            preise_ref = parent_doc_ref.collection("preise")
            for i, price in enumerate(sorted_prices):
                letter = chr(65 + i) if i < 26 else f"P{i}"
                sub_doc_ref = preise_ref.document(letter)
                batch.set(sub_doc_ref, price)
                doc_count += 1
                uploaded_count += 1

            if doc_count >= batch_size:
                batch.commit()
                print(f"Batch mit {doc_count} Dokumenten hochgeladen.")
                batch = db.batch()
                doc_count = 0

        if doc_count > 0:
            batch.commit()
            print(f"Letzter Batch mit {doc_count} Dokumenten hochgeladen.")

        print(f"Erfolgreich {uploaded_count} Dokumente hochgeladen.")

    except Exception as e:
        add_error_to_report("FIRESTORE_UPLOAD", f"Fehler beim Hochladen nach Firestore: {e}")
        print(f"Fehler beim Hochladen nach Firestore: {e}")
        raise


# --- HAUPTPROGRAMM STARTET HIER ---

print("\n=== STARTE ERWEITERTEN SCRAPING-PROZESS ===")

# --- SCHRITT 1: Spot-Preise von Gold.de scrapen ---
print("\n--- SCHRITT 1: Scraping Spot-Preise ---")
spot_prices = scrape_gold_spot_prices()

if spot_prices:
    print("Gefundene Spot-Preise:")
    for key, value in spot_prices.items():
        print(f"  {key}: {value}")
    
    # Spot-Preise nach Firestore hochladen
    upload_spot_prices_to_firestore(spot_prices)
else:
    print("Keine Spot-Preise gefunden.")

# --- SCHRITT 2: Produktpreise scrapen (bestehender Code) ---
print("\n--- SCHRITT 2: Scraping Produktpreise ---")

# --- CSV einlesen ---
csv_dir = ""
try:
    with open(os.path.join(csv_dir, "firesmall.csv"), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        daten = list(reader)
except FileNotFoundError:
    error_msg = f"Die Datei 'firesmall.csv' wurde nicht gefunden."
    add_error_to_report("FILE_NOT_FOUND", error_msg)
    print(f"Fehler: {error_msg}")
    create_report()
    exit()

MAX_INPUT_ENTRIES_TO_PROCESS = 4000
if len(daten) > MAX_INPUT_ENTRIES_TO_PROCESS:
    print(f"Warnung: Reduziere Eingaben von {len(daten)} auf {MAX_INPUT_ENTRIES_TO_PROCESS}")
    daten = daten[:MAX_INPUT_ENTRIES_TO_PROCESS]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- Scraping ---
coin_data = {}
for eintrag in daten:
    material = eintrag.get("Material", "").lower()
    art = eintrag.get("Art", "")
    name = eintrag.get("Name", "")
    stueckelung = eintrag.get("Stueckelung", "")
    jahrgaenge_roh = eintrag.get("Jahrgaenge", "").strip()
    jahrgaenge = [j.strip() for j in jahrgaenge_roh.split(",") if j.strip()] if jahrgaenge_roh else ["0"]

    entry_info = f"{name} {stueckelung} ({material})"

    if not (material and art and name and stueckelung):
        entries_skipped += 1
        add_error_to_report("MISSING_DATA", "Überspringe Eintrag aufgrund fehlender Daten", entry_info)
        continue

    for jahrgang in jahrgaenge:
        if request_count > 1 and request_count % 200 == 0:  # Geändert von 0 auf 1, da wir bereits 1 Anfrage für Spot-Preise haben
            print(f"\n--- Pause nach {request_count} Anfragen (10 Sekunden) ---")
            time.sleep(10)

        url = f"https://www.gold.de/ajax/schnellsuche.php?jahrgang={quote(jahrgang)}&stueckelung={quote(stueckelung)}&art={art}&anlageform=1&material={quote(material)}&preis=1&seite=0&invest=0&get_filter_ausf=std&form_extra=vkseite&func=produkte"
        print(f"Anfrage #{request_count + 1}: {name} {stueckelung} {jahrgang} ({material})")
        request_count += 1

        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            successful_requests += 1

            soup = BeautifulSoup(response.text, "html.parser")
            preis_divs = soup.find_all("div", class_="pv-preis")

            found_prices_count = 0
            key = create_coin_key(material, name, stueckelung, jahrgang)

            if key not in coin_data:
                coin_data[key] = {
                    "material": material,
                    "art": int(art) if art else 0,
                    "name": name,
                    "stueckelung": stueckelung,
                    "jahrgang": jahrgang,
                    "prices": []
                }

            if preis_divs:
                for preis_div in preis_divs:
                    if found_prices_count >= 5:
                        break
                    preis = None
                    if preis_div and preis_div.span:
                        try:
                            preis_text = preis_div.span.get_text(strip=True).replace(".", "").replace(",", ".").replace("€", "").strip()
                            preis = float(preis_text)
                        except ValueError:
                            continue

                    haendler = None
                    gramm_preis = None
                    spot_preis = None
                    product_container = preis_div.find_parent().find_parent() if preis_div.find_parent() else None
                    if product_container:
                        haendler_tag = product_container.find("a", class_="popoverhoverBewertung")
                        if haendler_tag:
                            haendler = haendler_tag.get_text(strip=True)
                        vs_info_div = product_container.find("div", class_="vs_info")
                        if vs_info_div:
                            info_pairs = vs_info_div.find_all("div", class_=["vs_info_left", "vs_info_right"])
                            for i in range(0, len(info_pairs), 2):
                                if i + 1 < len(info_pairs):
                                    label = info_pairs[i].get_text(strip=True)
                                    value = info_pairs[i + 1].get_text(strip=True)
                                    if "Gramm" in label:
                                        try:
                                            gramm_preis = float(value.replace(".", "").replace(",", ".").replace("€", "").strip())
                                        except ValueError:
                                            gramm_preis = None
                                    elif "Spotpreis" in label:
                                        spot_preis = value.strip()

                    if preis is not None:
                        price_dict = {
                            "haendler": haendler,
                            "preis": preis,
                            "gramm_preis": gramm_preis,
                            "spot_preis": spot_preis
                        }
                        coin_data[key]["prices"].append(price_dict)
                        found_prices_count += 1
                        prices_found_total += 1

        except requests.exceptions.Timeout:
            timeouts_count += 1
            add_error_to_report("TIMEOUT", "Timeout-Fehler", entry_info)
        except requests.exceptions.RequestException as req_err:
            request_exceptions_count += 1
            add_error_to_report("REQUEST_EXCEPTION", f"Anfragefehler: {req_err}", entry_info)
        except Exception as e:
            general_exceptions_count += 1
            add_error_to_report("GENERAL_EXCEPTION", f"Unerwarteter Fehler: {e}", entry_info)

        time.sleep(0.75)

print("\n--- Produktpreise-Scraping abgeschlossen ---")

# --- Backup-CSV schreiben ---
try:
    with open(TEMP_DATA_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        current_datum = datetime.now().strftime("%Y-%m-%d")
        for key, data in coin_data.items():
            for price in data["prices"]:
                writer.writerow([
                    data["material"],
                    data["art"],
                    data["name"],
                    data["jahrgang"],
                    data["stueckelung"],
                    price["preis"],
                    current_datum,
                    price["haendler"],
                    price["gramm_preis"],
                    price["spot_preis"]
                ])
    print(f"Backup-CSV '{TEMP_DATA_CSV_PATH}' erstellt.")
except Exception as e:
    add_error_to_report("CSV_WRITE", f"Fehler beim Schreiben der Backup-CSV: {e}")

upload_to_firestore(coin_data)

# --- Metadaten in "services1"-Sammlung ---
try:
    current_date = datetime.now().strftime("%Y-%m-%d")
    iso_timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "date_collection_name": current_date,
        "timestamp": iso_timestamp,
        "spot_prices_included": bool(spot_prices),
        "spot_prices_count": spot_prices_scraped
    }
    db.collection("services1").add(metadata)
    print(f"Metadaten in 'services1' mit Datum '{current_date}' erstellt.")
except Exception as e:
    add_error_to_report("METADATA_WRITE", f"Fehler beim Schreiben des Metadaten-Dokuments: {e}")

# --- CSV ins Backup verschieben ---
try:
    current_date = datetime.now().strftime("%Y-%m-%d")
    backup_filename = f"scraped_prices_{current_date}.csv"
    backup_file_path = os.path.join(BACKUP_FOLDER, backup_filename)
    if os.path.exists(TEMP_DATA_CSV_PATH):
        os.rename(TEMP_DATA_CSV_PATH, backup_file_path)
        print(f"CSV nach '{backup_file_path}' verschoben.")
    else:
        add_error_to_report("FILE_MOVE", f"Temporäre CSV '{TEMP_DATA_CSV_PATH}' nicht gefunden")
except OSError as e:
    add_error_to_report("FILE_MOVE", f"Fehler beim Verschieben: {e}")

report_filename = f"scraping_report_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
create_report(report_filename)

print("--- Alle Daten verarbeitet, nach Firestore übertragen und CSV gesichert. ---")
