import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

# --- CONFIGURATION TELEGRAM ---
TELEGRAM_TOKEN = "TON_TOKEN_ICI"
TELEGRAM_CHAT_ID = "TON_CHAT_ID_ICI"

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot8447447982:AAFVCd_yJsvHHC6Fl_5GYR75ziYVoEal3rw/sendMessage"
    payload = {"chat_id": 5844984041, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

# --- INITIALISATION MÉMOIRE ALERTES ---
if 'sent_alerts' not in st.session_state:
    st.session_state['sent_alerts'] = set()

# --- LOGIQUE DE RÉCUPÉRATION DES FLOORS ---
def get_segmented_floors(player_slug, is_in_season, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 40) {
          nodes { 
            senderSide { anyCards { rarityTyped seasonYear } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        lim_prices, rare_prices = [], []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            card_is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
            if card_is_in_season == is_in_season:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_prices.append(p)
                    if card['rarityTyped'] == 'rare': rare_prices.append(p)
        return (min(lim_prices) if lim_prices else None), (min(rare_prices) if rare_prices else None)
    except: return None, None

def scan_and_alert(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 80, sport: FOOTBALL) {
          nodes {
            senderSide { 
              anyCards { slug rarityTyped seasonYear anyPlayer { displayName slug } } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
                p_now = round(float(eur_cents) / 100, 2)
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in_season, jwt_token)
                
                ratio = round(p_now / f_lim, 2) if f_lim else 99
                card_id = card['slug'] # Identifiant unique de la mise en vente

                # --- LOGIQUE D'ALERTE TELEGRAM ---
                # On alerte si : Ratio < 3.5 ET pas encore envoyé
                if ratio < 3.5 and card_id not in st.session_state['sent_alerts']:
                    msg = (f"🚀 *PÉPITE DÉTECTÉE !*\n\n"
                           f"👤 Joueur : {card['anyPlayer']['displayName']}\n"
                           f"💰 Prix : {p_now}€ (Floor Rare: {f_rare}€)\n"
                           f"📊 Ratio : {ratio}\n"
                           f"🔗 [Acheter sur Sorare](https://sorare.com/football/cards/{card_id})")
                    send_telegram_alert(msg)
                    st.session_state['sent_alerts'].add(card_id)

                findings.append({
                    "🛒": f"https://sorare.com/football/cards/{card_id}",
                    "Vente": n.get('startDate'),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Saison": "🟢 In-Season" if is_in_season else "⚪ Classic",
                    "Prix (€)": p_now,
                    "Floor Rare (€)": f_rare,
                    "Ratio": ratio
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- UI ---
st.set_page_config(page_title="Sniper Telegram", layout="wide")
st.title("🎯 Sniper Sorare + Alertes Telegram")

if st.session_state.get('token'):
    st.sidebar.success("Bot Actif 🚀")
    st.sidebar.write(f"Dernier scan : {datetime.now().strftime('%H:%M:%S')}")
    
    data = scan_and_alert(st.session_state['token'])
    if data:
        df = pd.DataFrame(data)
        st.dataframe(df, column_config={"🛒": st.column_config.LinkColumn("🛒", display_text="Ouvrir")}, use_container_width=True)
    
    time.sleep(60)
    st.rerun()
