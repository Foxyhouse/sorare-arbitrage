import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime

# --- RÉCUPÉRATION DES SECRETS ---
# Streamlit va chercher ces variables dans l'onglet "Secrets" de ton dashboard
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
    DEFAULT_EMAIL = st.secrets["SORARE_EMAIL"]
    DEFAULT_PWD = st.secrets["SORARE_PASSWORD"]
except Exception as e:
    st.error("Erreur : Les secrets ne sont pas configurés dans Streamlit Cloud.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

# --- FONCTION ALERTE ---
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

# --- INITIALISATION ---
if 'sent_alerts' not in st.session_state:
    st.session_state['sent_alerts'] = set()
if 'token' not in st.session_state:
    st.session_state['token'] = None

# --- FONCTIONS API ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        return res.json().get("salt") if res.status_code == 200 else None
    except: return None

def sorare_sign_in(email, hashed_password):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") { token }
        errors { message }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {"input": {"email": email, "password": hashed_password}}}, timeout=10).json()
        return res.get('data', {}).get('signIn', {})
    except: return {}

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
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        lim_prices, rare_prices = [], []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            if (card.get('seasonYear') == CURRENT_SEASON_YEAR) == is_in_season:
                eur = n['receiverSide']['amounts']['eurCents']
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_prices.append(p)
                    if card['rarityTyped'] == 'rare': rare_prices.append(p)
        return min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None
    except: return None, None

def scan_and_alert(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFlux {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL) {
          nodes {
            senderSide { anyCards { slug rarityTyped seasonYear anyPlayer { displayName slug } } }
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
            eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            if eur and cards and cards[0]['rarityTyped'] == 'rare':
                card = cards[0]
                is_in = (card['seasonYear'] == CURRENT_SEASON_YEAR)
                p_now = round(float(eur) / 100, 2)
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in, jwt_token)
                
                ratio = round(p_now / f_lim, 2) if f_lim else 99
                
                # Alerte Telegram
                if ratio < 3.5 and card['slug'] not in st.session_state['sent_alerts']:
                    msg = f"🚀 *PÉPITE !* {card['anyPlayer']['displayName']} à {p_now}€ (Ratio: {ratio})\n[Lien](https://sorare.com/football/cards/{card['slug']})"
                    send_telegram_alert(msg)
                    st.session_state['sent_alerts'].add(card['slug'])

                findings.append({
                    "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                    "Vente": n['startDate'],
                    "Joueur": card['anyPlayer']['displayName'],
                    "Cat": "🟢 In" if is_in else "⚪ Cl",
                    "Prix": p_now,
                    "F.Rare": f_rare,
                    "Ratio": ratio
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Pro", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Initialiser la session Sorare"):
        salt = get_user_salt(DEFAULT_EMAIL)
        if salt:
            hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), salt.encode()).decode()
            res = sorare_sign_in(DEFAULT_EMAIL, hpwd)
            if res.get('jwtToken'):
                st.session_state['token'] = res['jwtToken']['token']
                st.rerun()
            else: st.error("Erreur de login (vérifie tes secrets ou OTP).")
else:
    st.sidebar.write(f"🔄 Auto-scan actif : {datetime.now().strftime('%H:%M:%S')}")
    if st.sidebar.button("Déconnexion"):
        st.session_state['token'] = None
        st.rerun()

    data = scan_and_alert(st.session_state['token'])
    if data:
        st.dataframe(pd.DataFrame(data), column_config={"🛒": st.column_config.LinkColumn("🛒", display_text="Ouvrir")}, use_container_width=True, hide_index=True)
    
    time.sleep(60)
    st.rerun()
