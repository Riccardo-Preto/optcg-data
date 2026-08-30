"""
generate_snapshot.py
=====================

COSA FA QUESTO SCRIPT (in parole semplici):
Va su optcgapi.com, scarica TUTTE le carte del gioco (set normali,
starter deck, promo, DON!!) e tutti i nomi dei set, e le salva in
un unico file "snapshot.json" ordinato e pulito.

Questo file JSON sarà la "fonte di verità" sia per la tua app Kotlin
che per il bot Discord: invece di scrivere migration SQL a mano ogni
volta che escono carte nuove, rigeneri questo file e lo pubblichi.

COME USARLO (la primissima volta):
1. Installa Python se non ce l'hai già: https://www.python.org/downloads/
   (durante l'installazione su Windows spunta "Add Python to PATH")
2. Apri un terminale (su Windows: cerca "cmd" o "PowerShell";
   su Mac: cerca "Terminale") nella cartella dove hai salvato questo file.
3. Installa la libreria che serve per fare le richieste web:
       pip install requests
4. Esegui lo script:
       python generate_snapshot.py
5. Alla fine troverai un file "snapshot.json" nella stessa cartella.
   Aprilo con un editor di testo per vedere come è fatto, se sei curioso.

Se qualcosa va storto, lo script stampa un messaggio chiaro su cosa
non ha funzionato (es. connessione assente, endpoint che non risponde).
"""

import json
import time
from datetime import datetime, timezone

import requests

BASE_URL = "https://optcgapi.com/api"

# Questi sono gli endpoint "prendi tutto" dell'API. Ognuno restituisce
# una lista di carte in formato JSON.
CARD_ENDPOINTS = {
    "set": f"{BASE_URL}/allSetCards/",       # carte dei booster set (OP01, OP02, ...)
    "starter_deck": f"{BASE_URL}/allSTCards/",  # carte degli starter deck (ST01, ST02, ...)
    "promo": f"{BASE_URL}/allPromos/",       # carte promozionali
    "don": f"{BASE_URL}/allDonCards/",       # carte DON!!
}

SET_ENDPOINTS = {
    "set": f"{BASE_URL}/allSets/",           # elenco dei booster set
    "starter_deck": f"{BASE_URL}/allDecks/", # elenco degli starter deck
}

# L'API a volte etichetta ancora qualche carta col vecchio set_id
# giapponese invece di quello della release occidentale (es. una carta
# di EB04 che in occidente è uscita dentro OP15EB04, non da sola; o
# delle promo da torneo etichettate "OP14" invece di "OP14EB04").
# Qui correggiamo questi casi noti alla fonte.
SET_ID_OVERRIDES = {
    "EB04": "OP15EB04",  # Monkey.D.Luffy (EB04-061, serial number)
    "OP14": "OP14EB04",  # 4 promo da torneo (Perona, Boa Hancock, Mihawk, Crocodile)
}


def fetch_json(url: str):
    """Scarica una pagina e la interpreta come JSON, con un messaggio
    d'errore comprensibile se qualcosa va storto."""
    print(f"  -> scarico {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()  # se il server risponde con un errore, si ferma qui
    return response.json()


def normalize_set_id(raw_set_id: str) -> str:
    """optcgapi.com usa 'OP-01' (con trattino), la tua app usa 'OP01'
    (senza trattino). Qui uniformiamo togliendo il trattino."""
    if not raw_set_id:
        return None
    return raw_set_id.replace("-", "")


def normalize_card(raw: dict) -> dict:
    """Converte una carta come arriva da optcgapi.com nel formato che
    usa già la tua tabella 'cards' in Room (stessi nomi di colonna
    che hai in Card.kt, così il codice Kotlin che scriveremo dopo
    è più semplice possibile)."""

    card_set_id = raw.get("card_set_id")
    card_image_id = raw.get("card_image_id") or card_set_id
    set_id = normalize_set_id(raw.get("set_id"))
    set_id = SET_ID_OVERRIDES.get(set_id, set_id)

    return {
        # id univoco della carta/variante — è quello che diventerà la
        # PrimaryKey nella tua tabella cards, esattamente come oggi.
        "id": card_image_id,
        "set_id": set_id,
        "nome": raw.get("card_name"),
        "card_color": raw.get("card_color"),
        "card_type": raw.get("card_type"),
        "card_cost": raw.get("card_cost"),
        "card_power": raw.get("card_power"),
        "counter_amount": raw.get("counter_amount"),
        "attribute": raw.get("attribute"),
        "rarity": raw.get("rarity"),
        "market_price": raw.get("market_price") or 0.0,
        "card_image": raw.get("card_image"),
        "api_image_id": card_image_id,
        "card_text": raw.get("card_text"),
        "sub_types": raw.get("sub_types") or "",
    }


def normalize_set(raw: dict, kind: str) -> dict:
    """Converte un set/starter deck nel formato della tua tabella 'sets'."""
    if kind == "starter_deck":
        raw_id = raw.get("structure_deck_id")
        name = raw.get("structure_deck_name")
    else:
        raw_id = raw.get("set_id")
        name = raw.get("set_name")

    return {
        "id": normalize_set_id(raw_id),
        "api_id": raw_id,
        "nome": name,
    }


def main():
    all_cards = {}   # usiamo un dizionario per id -> carta, così se una
                      # carta compare due volte non la duplichiamo
    all_sets = {}

    print("Scarico le carte...")
    for kind, url in CARD_ENDPOINTS.items():
        try:
            raw_cards = fetch_json(url)
        except Exception as exc:
            print(f"  ATTENZIONE: non sono riuscito a scaricare '{kind}' ({exc}). Continuo con il resto.")
            continue

        for raw in raw_cards:
            card = normalize_card(raw)
            if not card["id"]:
                continue

            # Alcune carte "promo" o "don" hanno lo stesso id di una carta
            # normale già vista (es. una ristampa promozionale con la
            # stessa sigla OP09-077 ma un'immagine diversa). Per non
            # perdere né sovrascrivere per sbaglio, se l'id è già
            # occupato da una carta DIVERSA (immagine diversa), le diamo
            # un id proprio invece di scartarla o sovrascrivere quella
            # buona.
            card_id = card["id"]
            if card_id in all_cards and all_cards[card_id]["card_image"] != card["card_image"]:
                suffix = 2
                new_id = f"{card_id}_alt{suffix}"
                while new_id in all_cards:
                    suffix += 1
                    new_id = f"{card_id}_alt{suffix}"
                card["id"] = new_id
                card["api_image_id"] = new_id

            all_cards[card["id"]] = card
        print(f"  ok: {len(raw_cards)} carte da '{kind}'")
        time.sleep(1)  # piccola pausa per non martellare l'API di qualcun altro

    print("Scarico i set...")
    for kind, url in SET_ENDPOINTS.items():
        try:
            raw_sets = fetch_json(url)
        except Exception as exc:
            print(f"  ATTENZIONE: non sono riuscito a scaricare i set '{kind}' ({exc}). Continuo con il resto.")
            continue

        for raw in raw_sets:
            s = normalize_set(raw, kind)
            if s["id"]:
                all_sets[s["id"]] = s
        print(f"  ok: {len(raw_sets)} set da '{kind}'")
        time.sleep(1)

    # Alcune carte (promo con set_id 'P', carte DON!! con set_id 'DON', ecc.)
    # appartengono a un "set_id" che non compare in nessuno dei due elenchi
    # sopra. La tua app ha una foreign key cards -> sets: se un set_id non
    # esiste nella tabella sets, l'inserimento della carta viene rifiutato.
    # Qui creiamo un set "segnaposto" per ognuno di questi id orfani, così
    # non si rompe mai nulla anche quando Bandai introduce categorie nuove.
    orphan_set_ids = {c["set_id"] for c in all_cards.values() if c["set_id"]} - set(all_sets.keys())
    for orphan_id in orphan_set_ids:
        all_sets[orphan_id] = {"id": orphan_id, "api_id": None, "nome": orphan_id}
    if orphan_set_ids:
        print(f"  creati {len(orphan_set_ids)} set segnaposto per id orfani: {sorted(orphan_set_ids)}")

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "card_count": len(all_cards),
        "set_count": len(all_sets),
        "cards": list(all_cards.values()),
        "sets": list(all_sets.values()),
    }

    with open("snapshot.json", "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"\nFatto! Salvate {len(all_cards)} carte e {len(all_sets)} set in snapshot.json")


if __name__ == "__main__":
    main()
