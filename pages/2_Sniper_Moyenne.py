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
    st.error("Erreur : Secrets manquants.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 
MIN_DISCOUNT_PERCENT = 20 

if 'token' not in st.session_state: st.session_state['token'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

# --- FONCTIONS DE SÉCURITÉ ---
def safe_get(obj, *keys):
    """Parcourt un dictionnaire de manière sécurisée."""
    for key in keys:
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
    return obj

def extract_price(amounts):
    """Extrait le prix en EUR d'une liste de prix."""
    if not isinstance(amounts, list): return None
    for a in amounts:
        if isinstance(a, dict) and a.get('eurCents'):
            return float(a['eurCents']) / 100
    return None

# --- LOGIQUE MÉTIER ---
def get_floor(slug, is_in, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:15){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'s': slug}}, headers=headers, timeout=10).json()
        nodes = safe_get(r, 'data', 'tokens', 'liveSingleSaleOffers', 'nodes') or []
        prices = []
        for n in nodes:
            cards = safe_get(n, 'senderSide', 'anyCards')
            if not cards: continue
            c = cards[0]
            if c.get('rarityTyped') == 'limited' and (c.get('seasonYear') == CURRENT_SEASON_YEAR) == is_in:
                p = extract_price(safe_get(n, 'receiverSide', 'amounts'))
                if p: prices.append(p)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query g{tokens{liveSingleSaleOffers(first:60,sport:FOOTBALL){nodes{startDatereceiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_FIFTEEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = safe_get(r, 'data', 'tokens', 'liveSingleSaleOffers', 'nodes')
        if not isinstance(nodes, list): return []
        
        # Tri par date
        nodes.sort(key=lambda x: x.get('startDate', '') if isinstance(x, dict) else '', reverse=True)
        
        findings = []
        now = datetime.now(tz.tzutc())

        for n in nodes:
            if not isinstance(n, dict): continue
            cards = safe_get(n, 'senderSide', 'anyCards')
            if not cards or cards[0].get('rarityTyped') != 'limited': continue
            
            p_now = extract_price(safe_get(n, 'receiverSide', 'amounts'))
            if not p_now: continue

            player = cards[0].get('anyPlayer', {})
            l15 = player.get('averageScore', 0)
            if not l15 or l15 == 0: continue

            is_in = cards[0].get('seasonYear') == CURRENT_SEASON_YEAR
            
            # Temps
            try:
                start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
                age = int((now - start_dt).total_seconds() // 60)
            except: age = 999
            if age > 120: continue 

            floor = get_floor(player.get('slug'), is_in, jwt_token, p_now)
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                if discount > -100:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                        "Âge": f"{age} min",
                        "Joueur": player.get('displayName'),
                        "L15": l15,
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_d": n['startDate']
                    })
                    if discount >= MIN_DISCOUNT_PERCENT and cards[0]['slug'] not in st.session_state['sent_alerts']:
                        msg = f"🚀 SNIPE : {player.get('displayName')} -{discount}% ({p_now}€)"
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
                        st.session_state['sent_alerts'].add(cards[0]['slug'])
        return findings
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper V3.1", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Connexion"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        q = """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}"""
        res = requests.post(API_URL, json={'query': q, 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = safe_get(res, 'data', 'signIn', 'jwtToken', 'token')
        st.rerun()
else:
    st.sidebar.success("Scanner ON")
    data = scan_flux(st.session_state['token'])
    if data:
        df = pd.DataFrame(data).drop(columns=['_d'])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Attente de nouvelles cartes...")
    time.sleep(60)
    st.rerun()
