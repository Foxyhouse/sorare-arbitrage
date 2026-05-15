import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime
from dateutil import tz

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
    # Ici on ne trie pas, on veut juste les prix les plus bas existants
    query = """query f($s:String!){tokens{liveSingleSaleOffers(playerSlug:$s,first:15){nodes{senderSide{anyCards{rarityTyped seasonYear}}receiverSide{amounts{eurCents}}}}}}"""
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
    # 🚨 LA CORRECTION EST ICI : Ajout de sort: NEWEST
    query = """query g{tokens{liveSingleSaleOffers(first:80, sport:FOOTBALL, sort:NEWEST){nodes{startDate receiverSide{amounts{eurCents}}senderSide{anyCards{slug rarityTyped seasonYear anyPlayer{displayName slug averageScore(type:LAST_FIFTEEN_SO5_AVERAGE_SCORE)}}}}}}}"""
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        if not nodes: return []
        
        findings = []
        now = datetime.now(tz.tzutc())
        
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards or cards[0]['rarityTyped'].lower() != 'limited': continue
            
            p_now = get_price(n)
            if not p_now: continue
            
            player = cards[0]['anyPlayer']
            l15 = player.get('averageScore', 0)
            if not l15 or l15 == 0: continue
            
            is_in = (cards[0]['seasonYear'] == CURRENT_SEASON_YEAR)
            
            # Calcul de l'âge réel
            start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
            age_min = int((now - start_dt).total_seconds() // 60)
            
            # On ne veut que ce qui est ultra récent (moins de 30 min pour le tableau)
            if age_min > 30: continue 

            floor = get_floor(player['slug'], is_in, jwt_token, p_now)
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                
                # On affiche tout ce qui a un discount positif
                if discount > 0: 
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                        "Posté il y a": f"{age_min} min",
                        "Joueur": player['displayName'],
                        "L15": l15,
                        "Cat": "In-Season" if is_in else "Classic",
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_raw_date": n['startDate']
                    })
                    
                    if discount >= 20 and cards[0]['slug'] not in st.session_state['sent_alerts']:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", 
                                      json={"chat_id": TELEGRAM_CHAT_ID, "text": f"🎯 SNIPE : {player['displayName']} -{discount}% ({p_now}€)"})
                        st.session_state['sent_alerts'].add(cards[0]['slug'])
        
        return sorted(findings, key=lambda x: x['_raw_date'], reverse=True)
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper New Listings", layout="wide")

if not st.session_state['token']:
    if st.button("🚀 Lancer le Scanner"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        res = requests.post(API_URL, json={'query': """mutation s($i:signInInput!){signIn(input:$i){jwtToken(aud:"sorare-app"){token}}}""", 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
        st.rerun()
else:
    st.sidebar.success("📡 Scan des nouveautés en cours")
    data = scan_flux(st.session_state['token'])
    if data:
        st.dataframe(pd.DataFrame(data).drop(columns=['_raw_date']), 
                     column_config={"🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir")}, 
                     use_container_width=True, hide_index=True)
    else:
        st.info("Rien de neuf sur le marché Limited (L15 > 0) depuis 30 min. Je surveille...")
    
    time.sleep(60)
    st.rerun()
