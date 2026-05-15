import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime
from dateutil import tz

# --- CONFIGURATION ---
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
def safe_get(obj, *keys):
    for key in keys:
        if isinstance(obj, dict): obj = obj.get(key)
        else: return None
    return obj

def extract_price(amounts):
    if not isinstance(amounts, list): return None
    for a in amounts:
        if isinstance(a, dict) and a.get('eurCents'): return float(a['eurCents']) / 100
    return None

# --- CORE ---
def get_floor_debug(slug, is_in, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:15){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'s': slug}}, headers=headers, timeout=10).json()
        nodes = safe_get(r, 'data', 'tokens', 'liveSingleSaleOffers', 'nodes') or []
        prices = []
        for n in nodes:
            cards = safe_get(n, 'senderSide', 'anyCards') or []
            if not cards: continue
            c = cards[0]
            # On compare le floor sur la même catégorie (In-Season / Classic)
            if str(c.get('rarityTyped')).lower() == 'limited' and (c.get('seasonYear') == CURRENT_SEASON_YEAR) == is_in:
                p = extract_price(safe_get(n, 'receiverSide', 'amounts'))
                if p: prices.append(p)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_diagnostic(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query g{tokens{liveSingleSaleOffers(first:80,sport:FOOTBALL){nodes{startDate receiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_FIFTEEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = safe_get(r, 'data', 'tokens', 'liveSingleSaleOffers', 'nodes')
        if not nodes: return []
        
        nodes.sort(key=lambda x: x.get('startDate', ''), reverse=True)
        findings = []
        now = datetime.now(tz.tzutc())

        for n in nodes:
            cards = safe_get(n, 'senderSide', 'anyCards') or []
            if not cards: continue
            
            # On vérifie la rareté sans être trop sensible à la casse
            rarity = str(cards[0].get('rarityTyped')).lower()
            if rarity != 'limited': continue
            
            p_now = extract_price(safe_get(n, 'receiverSide', 'amounts'))
            if not p_now: continue

            player = cards[0].get('anyPlayer') or {}
            l15 = player.get('averageScore', 0)
            is_in = (cards[0].get('seasonYear') == CURRENT_SEASON_YEAR)
            
            # Calcul du temps (on élargit à 4h pour être sûr de voir du monde)
            try:
                start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
                age = int((now - start_dt).total_seconds() // 60)
            except: age = 999
            if age > 240: continue 

            floor = get_floor_debug(player.get('slug'), is_in, jwt_token, p_now)
            
            # Calcul de la décote (on autorise tout pour le debug)
            discount = 0.0
            if floor:
                discount = round(((floor - p_now) / floor) * 100, 1)

            # ON AFFICHE TOUT (Même si discount < 0 ou L15 = 0)
            findings.append({
                "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                "Âge": f"{age} min",
                "Joueur": player.get('displayName', 'Inconnu'),
                "L15": l15,
                "Cat": "In-Season" if is_in else "Classic",
                "Prix (€)": p_now,
                "Floor (€)": floor,
                "Décote (%)": discount,
                "_d": n['startDate']
            })
            
        return findings
    except Exception as e:
        st.error(f"Erreur : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Sniper Diag", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Connexion"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        q = """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}"""
        res = requests.post(API_URL, json={'query': q, 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = safe_get(res, 'data', 'signIn', 'jwtToken', 'token')
        st.rerun()
else:
    st.sidebar.write(f"Dernière maj : {datetime.now().strftime('%H:%M:%S')}")
    data = scan_diagnostic(st.session_state['token'])
    if data:
        st.dataframe(pd.DataFrame(data).drop(columns=['_d']), use_container_width=True, hide_index=True)
    else:
        st.warning("Aucune carte Limited trouvée dans les 4 dernières heures.")
    
    time.sleep(60)
    st.rerun()
