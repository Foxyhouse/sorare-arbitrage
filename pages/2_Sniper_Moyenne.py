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

# --- SESSION ---
if 'token' not in st.session_state: st.session_state['token'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

# --- HELPERS ---
def get_eur_price(amounts_list):
    """Extrait proprement le prix en EUR parmi les devises (ETH, EUR, etc.)"""
    for price in amounts_list:
        if price.get('eurCents'):
            return float(price['eurCents']) / 100
    return None

def get_floor_price(player_slug, is_in_season, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFloor($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 15) {
          nodes { 
            senderSide { anyCards { rarityTyped seasonYear } }
            receiverSide { amounts { eurCents } } 
          }
        }
      }
    }
    """
    try:
        r = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            if card['rarityTyped'] == 'limited' and (card['seasonYear'] == CURRENT_SEASON_YEAR) == is_in_season:
                p = get_eur_price(n['receiverSide']['amounts'])
                if p: prices.append(p)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetRecent {
      tokens {
        liveSingleSaleOffers(first: 60, sport: FOOTBALL) {
          nodes {
            startDate
            receiverSide { amounts { eurCents } }
            senderSide {
              anyCards {
                slug
                rarityTyped
                seasonYear
                anyPlayer { displayName slug averageScore(type: LAST_FIFTEEN_SO5_AVERAGE_SCORE) }
              }
            }
          }
        }
      }
    }
    """
    try:
        r = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = r.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        # Tri immédiat par date
        nodes.sort(key=lambda x: x.get('startDate', ''), reverse=True)
        
        findings = []
        now = datetime.now(tz.tzutc())

        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards or cards[0]['rarityTyped'] != 'limited': continue
            
            p_now = get_eur_price(n['receiverSide']['amounts'])
            if not p_now: continue

            player = cards[0]['anyPlayer']
            l15 = player.get('averageScore', 0)
            if not l15 or l15 == 0: continue

            is_in = cards[0]['seasonYear'] == CURRENT_SEASON_YEAR
            
            # Temps écoulé
            start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
            diff_min = int((now - start_dt).total_seconds() // 60)
            if diff_min > 120: continue # On regarde les 2 dernières heures

            floor = get_floor_price(player['slug'], is_in, jwt_token, p_now)
            
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                
                # J'affiche tout > 0 pour voir si ça mord
                if discount > 0:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{cards[0]['slug']}",
                        "Âge": f"{diff_min} min",
                        "Joueur": player['displayName'],
                        "L15": l15,
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_ts": n['startDate']
                    })
                    
                    if discount >= MIN_DISCOUNT_PERCENT and cards[0]['slug'] not in st.session_state['sent_alerts']:
                        msg = f"🚀 SNIPE : {player['displayName']} -{discount}% ({p_now}€)"
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
                        st.session_state['sent_alerts'].add(cards[0]['slug'])

        return findings
    except Exception as e:
        st.error(f"Erreur : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Sniper V3", layout="wide")

if st.session_state['token'] is None:
    if st.button("🚀 Connexion Rapide"):
        r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
        q = """mutation s($i: signInInput!){ signIn(input: $i){ jwtToken(aud: "sorare-app"){ token } } }"""
        res = requests.post(API_URL, json={'query': q, 'variables': {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}}).json()
        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
        st.rerun()
else:
    st.sidebar.success("Radar Nouveautés ON")
    data = scan_flux(st.session_state['token'])
    if data:
        df = pd.DataFrame(data).drop(columns=['_ts'])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Attente de nouvelles cartes Limited (L15 > 0)...")
    
    time.sleep(60)
    st.rerun()
