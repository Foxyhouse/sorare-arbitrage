import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime, timedelta
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
MIN_DISCOUNT_PERCENT = 15 # On baisse un peu pour voir plus de résultats au début

if 'token' not in st.session_state: st.session_state['token'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

# --- EXTRACTION DU PRIX (BÉTONNÉE) ---
def get_price(node):
    try:
        # On cherche dans receiverSide -> amounts
        amounts = node.get('receiverSide', {}).get('amounts', [])
        if amounts and isinstance(amounts, list):
            for a in amounts:
                if a.get('eurCents'):
                    return float(a['eurCents']) / 100
        return None
    except: return None

# --- RÉCUPÉRATION DU FLOOR ---
def get_floor(slug, is_in, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:15){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'s': slug}}, headers=headers, timeout=10).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            c = cards[0]
            if c['rarityTyped'].lower() == 'limited' and (c['seasonYear'] == CURRENT_SEASON_YEAR) == is_in:
                p = get_price(n)
                if p: prices.append(p)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

# --- LE SCANNER ---
def scan_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # On demande 100 cartes pour être sûr d'avoir les toutes dernières dans le lot
    query = """query g{tokens{liveSingleSaleOffers(first:100,sport:FOOTBALL){nodes{startDate receiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_TEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        if not nodes: return []

        # 🚨 TRI PAR DATE DE DÉBUT (La plus récente en premier)
        nodes.sort(key=lambda x: x.get('startDate', ''), reverse=True)
        
        findings = []
        now_utc = datetime.now(tz.tzutc())

        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards or cards[0]['rarityTyped'].lower() != 'limited': continue
            
            p_now = get_price(n)
            if not p_now: continue

            player = cards[0]['anyPlayer']
            l10 = player.get('averageScore', 0)
            
            # --- FILTRE 1 : L10 > 0 ---
            if not l10 or l10 == 0: continue

            is_in = (cards[0]['seasonYear'] == CURRENT_SEASON_YEAR)
            
            # --- CALCUL DE L'ÂGE ---
            start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
            age_min = int((now_utc - start_dt).total_seconds() // 60)
            
            # --- FILTRE 2 : Nouveautés uniquement (moins de 2 heures) ---
            if age_min > 120: continue 

            floor = get_floor(player['slug'], is_in, jwt_token, p_now)
            
            # --- FILTRE 3 : Rentabilité Floor > 1.10€ ---
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                
                # --- FILTRE 4 : Uniquement les vraies décotes ---
                if discount > 0:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                        "Âge": f"{age_min} min",
                        "Joueur": player['displayName'],
                        "L10": l10,
                        "Cat": "In-Season" if is_in else "Classic",
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_raw_date": n['startDate']
                    })
                    
                    if discount >= MIN_DISCOUNT_PERCENT and cards[0]['slug'] not in st.session_state['sent_alerts']:
                        msg = f"🚀 SNIPE {discount}% : {player['displayName']} à {p_now}€ (Floor: {floor}€)"
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
                        st.session_state['sent_alerts'].add(cards[0]['slug'])

        return findings
    except Exception as e:
        st.sidebar.error(f"Erreur API : {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Final", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Connexion"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        q = """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}"""
        res = requests.post(API_URL, json={'query': q, 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
        st.rerun()
else:
    st.sidebar.success("Scanner Actif")
    st.sidebar.write(f"Dernière maj : {datetime.now().strftime('%H:%M:%S')}")
    
    data = scan_flux(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data).drop(columns=['_raw_date'])
        
        # Style couleurs
        def color_decote(val):
            color = 'white'
            if val >= 25: color = '#28a745' # Vert
            elif val >= 15: color = '#ffc107' # Jaune
            return f'background-color: {color}'

        st.dataframe(
            df.style.applymap(color_decote, subset=['Décote (%)']), 
            column_config={"🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir")},
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("Recherche de nouvelles pépites... (Limited, L10 > 0, Floor > 1.10€)")
    
    time.sleep(60)
    st.rerun()
