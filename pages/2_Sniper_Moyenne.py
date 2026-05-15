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
except Exception as e:
    st.error("Erreur : Configurez vos secrets.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 
MIN_DISCOUNT_PERCENT = 20 

# --- ÉTAT DE LA SESSION ---
if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_needed' not in st.session_state: st.session_state['otp_needed'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

# --- FONCTIONS UTILITAIRES ---
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5)
    except: pass

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") { token }
        otpSessionChallenge
      }
    }
    """
    variables = {"input": {"otpSessionChallenge": otp_challenge, "otpAttempt": otp_attempt}} if otp_challenge else {"input": {"email": email, "password": hashed_password}}
    try: return requests.post(API_URL, json={'query': query, 'variables': variables}, timeout=10).json().get('data', {}).get('signIn', {})
    except: return {}

def get_floor_discount(player_slug, is_in_season, rarity_typed, jwt_token, p_now):
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
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        prices = []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            if card['rarityTyped'].lower() == rarity_typed.lower() and (card['seasonYear'] == CURRENT_SEASON_YEAR) == is_in_season:
                prices.append(float(n['receiverSide']['amounts'][0]['eurCents']) / 100)
        prices.sort()
        if p_now in prices: prices.remove(p_now)
        return prices[0] if prices else None
    except: return None

# --- SCANNER : FOCUS NOUVEAUTÉS ---
def scan_recent_cards(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # 🚨 CHANGEMENT DE REQUÊTE : On cherche par tokens mis en vente récemment
    query = """
    query GetNewListings {
      tokens {
        liveSingleSaleOffers(first: 50, sport: FOOTBALL) {
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
        res = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        # 🚨 TRI MANUEL PAR DATE DE DÉBUT (Le plus récent en premier)
        nodes.sort(key=lambda x: x['startDate'], reverse=True)
        
        findings = []
        now = datetime.now(tz.tzutc())

        for n in nodes:
            cards = n['senderSide']['anyCards']
            if not cards or cards[0]['rarityTyped'] != 'limited': continue
            
            card = cards[0]
            player = card['anyPlayer']
            l15 = player.get('averageScore', 0)
            if not l15 or l15 == 0: continue

            p_now = float(n['receiverSide']['amounts'][0]['eurCents']) / 100
            is_in = card['seasonYear'] == CURRENT_SEASON_YEAR
            
            # Temps depuis la mise en vente
            start_dt = datetime.strptime(n['startDate'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
            diff = now - start_dt
            
            # Si la carte a plus de 30 minutes, on considère que ce n'est plus un "snipe" tout frais
            # (Optionnel : tu peux commenter cette ligne pour tout voir)
            if diff.total_seconds() > 1800: continue 

            floor = get_floor_discount(player['slug'], is_in, 'limited', jwt_token, p_now)
            
            if floor and floor >= 1.10:
                discount = round(((floor - p_now) / floor) * 100, 1)
                
                # On n'affiche que les opportunités (ou debug à -100)
                if discount > -100: 
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                        "Depuis": f"{int(diff.total_seconds() // 60)} min",
                        "Joueur": player['displayName'],
                        "L15": l15,
                        "Prix (€)": p_now,
                        "Floor (€)": floor,
                        "Décote (%)": discount,
                        "_sort": n['startDate']
                    })
                    
                    if discount >= MIN_DISCOUNT_PERCENT and card['slug'] not in st.session_state['sent_alerts']:
                        send_telegram_alert(f"🚀 SNIPE : {player['displayName']} -{discount}% à {p_now}€")
                        st.session_state['sent_alerts'].add(card['slug'])

        return findings
    except Exception as e:
        st.error(f"Erreur API : {e}")
        return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Sniper Instantané", layout="wide")

if st.session_state['token'] is None:
    st.title("🔐 Connexion")
    if st.button("🚀 Sign In"):
        res = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
        hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), res['salt'].encode()).decode()
        res_sign = sorare_sign_in(DEFAULT_EMAIL, hpwd)
        if res_sign.get('jwtToken'):
            st.session_state['token'] = res_sign['jwtToken']['token']
            st.rerun()
else:
    st.sidebar.success("Scanner Actif - Focus Nouveautés")
    data = scan_recent_cards(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data).drop(columns=['_sort'])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune nouvelle carte Limited avec L15 > 0 détectée ces 30 dernières minutes.")

    time.sleep(60)
    st.rerun()
