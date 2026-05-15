import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime, timedelta
from dateutil import tz

# --- CONFIG ---
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
    DEFAULT_EMAIL = st.secrets["SORARE_EMAIL"]
    DEFAULT_PWD = st.secrets["SORARE_PASSWORD"]
except:
    st.error("Secrets manquants dans le dashboard Streamlit.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

if 'token' not in st.session_state: st.session_state['token'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

def get_price(node):
    try:
        amounts = node.get('receiverSide', {}).get('amounts', [])
        for a in amounts:
            if a.get('eurCents'): return float(a['eurCents']) / 100
        return None
    except: return None

def get_floor(slug, is_in, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:10){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'s': slug}}, headers=headers, timeout=10).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = [get_price(n) for n in nodes if get_price(n)]
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # On retire le sort:NEWEST qui fait tout planter et on augmente le quota
    query = """query g{tokens{liveSingleSaleOffers(first:100, sport:FOOTBALL){nodes{startDate receiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_FIFTEEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        if not nodes: return []
        
        # TRI PYTHON PAR DATE DE CRÉATION
        nodes.sort(key=lambda x: x.get('startDate', ''), reverse=True)
        
        findings = []
        now = datetime.now(tz.tzutc())
        
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards or cards[0]['rarityTyped'].lower() != 'limited': continue
            
            p_now = get_price(n)
            if not p_now: continue
            
            player = cards[0]['anyPlayer']
            l15 = player.get('averageScore', 0)
            is_in = (cards[0]['seasonYear'] == CURRENT_SEASON_YEAR)
            
            # Calcul de l'âge
            start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
            age_min = int((now - start_dt).total_seconds() // 60)
            
            # On élargit à 4 heures pour voir si ça mord !
            if age_min > 240: continue 

            floor = get_floor(player['slug'], is_in, jwt_token, p_now)
            
            # Calcul de la décote
            discount = 0
            if floor:
                discount = round(((floor - p_now) / floor) * 100, 1)

            # --- ON AFFICHE TOUT POUR VÉRIFIER LE FLUX ---
            findings.append({
                "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                "Âge": f"{age_min} min",
                "Joueur": player['displayName'],
                "L15": l15,
                "Cat": "In-Season" if is_in else "Classic",
                "Prix (€)": p_now,
                "Floor (€)": floor,
                "Décote (%)": discount,
                "_raw_date": n['startDate']
            })
            
            # Alerte Telegram uniquement sur les vraies affaires (>20%)
            if discount >= 20 and cards[0]['slug'] not in st.session_state['sent_alerts']:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🔥 OPPORTUNITÉ : {player['displayName']} -{discount}% à {p_now}€"})
                st.session_state['sent_alerts'].add(cards[0]['slug'])
        
        return findings
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Wide View", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Se connecter et Scanner"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        res = requests.post(API_URL, json={'query': """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}""", 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
        st.rerun()
else:
    st.sidebar.success("📡 Scanner en mode LARGE (4h)")
    data = scan_flux(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data).drop(columns=['_raw_date'])
        
        def color_decote(val):
            if val >= 20: return 'background-color: #28a745; color: white'
            if val > 0: return 'background-color: #d4edda'
            if val < 0: return 'color: #dc3545'
            return ''

        st.dataframe(df.style.applymap(color_decote, subset=['Décote (%)']), 
                     column_config={"🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir")}, 
                     use_container_width=True, hide_index=True)
    else:
        st.warning("Aucune carte Limited détectée. Vérifie ta connexion Sorare.")
    
    time.sleep(60)
    st.rerun()
