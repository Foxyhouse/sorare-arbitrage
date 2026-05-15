import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime, timedelta
from dateutil import tz

# --- CONFIGURATION (SECRETS) ---
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

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def get_floor_price(player_slug, is_in_season, rarity, jwt_token, p_now):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFloor($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 20) {
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
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            card = cards[0]
            if card['rarityTyped'].lower() == rarity.lower() and (card['seasonYear'] == CURRENT_SEASON_YEAR) == is_in_season:
                amounts = n.get('receiverSide', {}).get('amounts', [])
                if amounts:
                    prices.append(float(amounts[0]['eurCents']) / 100)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

def scan_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetRecent {
      tokens {
        liveSingleSaleOffers(first: 80, sport: FOOTBALL) {
          nodes {
            startDate
            receiverSide { amounts { eurCents } }
            senderSide {
              anyCards {
                slug
                rarityTyped
                seasonYear
                anyPlayer {
                  displayName
                  slug
                  averageScore(type: LAST_FIFTEEN_SO5_AVERAGE_SCORE)
                }
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
        
        # Tri par date de début (les plus récents en haut)
        nodes.sort(key=lambda x: x.get('startDate', ''), reverse=True)
        
        findings = []
        now = datetime.now(tz.tzutc())

        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            amounts = n.get('receiverSide', {}).get('amounts', [])
            if not cards or not amounts: continue
            
            card = cards[0]
            if card['rarityTyped'] != 'limited': continue
            
            player = card['anyPlayer']
            l15 = player.get('averageScore', 0)
            if not l15 or l15 == 0: continue

            p_now = float(amounts[0]['eurCents']) / 100
            is_in = card['seasonYear'] == CURRENT_SEASON_YEAR
            
            # Calcul du temps écoulé
            try:
                start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
                diff_min = int((now - start_dt).total_seconds() // 60)
            except: diff_min = 999

            # On ne garde que les nouveautés de moins de 60 min pour être réactif
            if diff_min > 60: continue 

            floor = get_floor_price(player['slug'], is_in, 'limited', jwt_token, p_now)
            
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                
                # J'affiche tout ce qui est > -100 pour que tu vois le tableau bouger
                if discount > -100:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                        "Âge": f"{diff_min} min",
                        "Joueur": player['displayName'],
                        "L15": l15,
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_date": n['startDate']
                    })
                    
                    if discount >= MIN_DISCOUNT_PERCENT and card['slug'] not in st.session_state['sent_alerts']:
                        send_telegram_alert(f"🚀 SNIPE : {player['displayName']} -{discount}% ({p_now}€)")
                        st.session_state['sent_alerts'].add(card['slug'])

        return findings
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Sniper V2", layout="wide")

if st.session_state['token'] is None:
    if st.button("🚀 Connexion Sorare"):
        try:
            r_salt = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
            hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), r_salt['salt'].encode()).decode()
            
            q_sign = """mutation s($i: signInInput!){ signIn(input: $i){ jwtToken(aud: "sorare-app"){ token } } }"""
            v_sign = {"i": {"email": DEFAULT_EMAIL, "password": hpwd}}
            res = requests.post(API_URL, json={'query': q_sign, 'variables': v_sign}).json()
            
            st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
            st.rerun()
        except: st.error("Échec connexion.")
else:
    st.sidebar.success("Scanner Nouveautés Actif")
    results = scan_flux(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['_date'])
        
        def color_decote(val):
            color = 'white'
            if val >= 25: color = '#28a745'
            elif val >= 15: color = '#ffc107'
            return f'background-color: {color}'

        st.dataframe(df.style.applymap(color_decote, subset=['Décote (%)']), use_container_width=True, hide_index=True)
    else:
        st.info("Recherche de nouvelles mises en vente (Limited, L15 > 0)...")

    time.sleep(60)
    st.rerun()
