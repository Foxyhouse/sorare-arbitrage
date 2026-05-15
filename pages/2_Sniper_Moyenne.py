import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime

# --- CONFIG ---
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
    DEFAULT_EMAIL = st.secrets["SORARE_EMAIL"]
    DEFAULT_PWD = st.secrets["SORARE_PASSWORD"]
except:
    st.error("Secrets manquants.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

if 'token' not in st.session_state: st.session_state['token'] = None

# --- SÉCURITÉ ---
def extract_price(amounts):
    if not isinstance(amounts, list): return None
    for a in amounts:
        if isinstance(a, dict) and a.get('eurCents'): return float(a['eurCents']) / 100
    return None

# --- CORE ---
def get_floor_simple(slug, is_in, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:10){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'s': slug}}, headers=headers, timeout=10).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = []
        for n in nodes:
            c = n['senderSide']['anyCards'][0]
            if c['rarityTyped'].lower() == 'limited' and (c['seasonYear'] == CURRENT_SEASON_YEAR) == is_in:
                p = extract_price(n['receiverSide']['amounts'])
                if p: prices.append(p)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_brut(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # Requête ultra-simplifiée
    query = """query g{tokens{liveSingleSaleOffers(first:50,sport:FOOTBALL){nodes{startDate receiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_FIFTEEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        if not nodes:
            st.warning("L'API Sorare a renvoyé une liste vide.")
            return []

        findings = []
        for n in nodes:
            try:
                card = n['senderSide']['anyCards'][0]
                # Filtre Limited uniquement
                if card['rarityTyped'].lower() != 'limited': continue
                
                p_now = extract_price(n['receiverSide']['amounts'])
                player = card['anyPlayer']
                is_in = (card['seasonYear'] == CURRENT_SEASON_YEAR)
                
                # On récupère le floor SANS condition
                floor = get_floor_simple(player['slug'], is_in, jwt_token, p_now)
                
                discount = 0.0
                if floor:
                    discount = round(((floor - p_now) / floor) * 100, 1)

                findings.append({
                    "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                    "Date": n['startDate'],
                    "Joueur": player['displayName'],
                    "L15": player.get('averageScore', 0),
                    "Cat": "In-Season" if is_in else "Classic",
                    "Prix (€)": p_now,
                    "Floor (€)": floor,
                    "Décote (%)": discount
                })
            except: continue
            
        # Tri par date (les plus récents en haut - texte brut pour éviter les bugs de fuseau)
        return sorted(findings, key=lambda x: x['Date'], reverse=True)
    except Exception as e:
        st.error(f"Erreur : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Sniper Brut", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Connexion"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        q = """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}"""
        res = requests.post(API_URL, json={'query': q, 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
        st.rerun()
else:
    st.sidebar.write(f"Vérification : {datetime.now().strftime('%H:%M:%S')}")
    data = scan_brut(st.session_state['token'])
    
    if data:
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
    else:
        st.info("Toujours rien... tentative de reconnexion au flux.")
    
    time.sleep(60)
    st.rerun()
