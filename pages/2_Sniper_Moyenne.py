import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime
from dateutil import tz

# --- CONFIGURATION (SECRETS) ---
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
    DEFAULT_EMAIL = st.secrets["SORARE_EMAIL"]
    DEFAULT_PWD = st.secrets["SORARE_PASSWORD"]
except Exception as e:
    st.error("Erreur : Configurez vos secrets dans le dashboard Streamlit.")
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
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 20) {
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
        nodes = res.get('data', {}).get('tokens', {}).get('all_offers', {}).get('nodes', [])
        valid_prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards')
            if not cards: continue
            card = cards[0]
            card_is_in = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
            if str(card.get('rarityTyped')).lower() == rarity_typed.lower() and card_is_in == is_in_season:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    valid_prices.append(round(float(eur) / 100, 2))
        valid_prices.sort()
        if p_now in valid_prices:
            valid_prices.remove(p_now)
        if len(valid_prices) > 0:
            return valid_prices[0], len(valid_prices)
        return None, 0
    except: return None, 0

# --- SCANNER DE DÉCOTE (FLUX DES NOUVEAUTÉS) ---
def scan_discount_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # 🚨 MISE À JOUR : On trie par date de début descendante pour avoir les NOUVELLES cartes
    query = """
    query GetRecentFlux {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL, sort: NEWEST) {
          nodes {
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
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers, timeout=15).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        
        for n in nodes:
            eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            
            if eur and cards and str(cards[0].get('rarityTyped')).lower() == 'limited':
                card = cards[0]
                l15 = card['anyPlayer'].get('averageScore')
                
                # Filtre L15 > 0
                if not l15 or float(l15) == 0.0:
                    continue
                    
                is_in = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
                p_now = round(float(eur) / 100, 2)
                
                true_floor, nb_market = get_floor_discount(card['anyPlayer']['slug'], is_in, 'limited', jwt_token, p_now)
                
                # Filtre rentabilité Floor > 1.10€
                if true_floor is None or true_floor < 1.10:
                    continue
                
                discount_pct = round(((true_floor - p_now) / true_floor) * 100, 1)
                
                # Heure Locale
                raw_date = n.get('startDate', "")
                try:
                    # Format Sorare : 2026-05-15T15:39:51Z
                    utc_dt = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
                    local_dt = utc_dt.astimezone(tz.tzlocal())
                    formatted_time = local_dt.strftime("%H:%M:%S")
                    timestamp = local_dt.timestamp()
                except: 
                    formatted_time = raw_date
                    timestamp = 0

                # Alerte Telegram
                if discount_pct >= MIN_DISCOUNT_PERCENT and card['slug'] not in st.session_state['sent_alerts']:
                    msg = (f"🟨 *NOUVEAU SNIPE : -{discount_pct}%*\n\n"
                           f"👤 {card['anyPlayer']['displayName']} (L15: {l15})\n"
                           f"💰 Prix : {p_now}€ (Floor: {true_floor}€)\n"
                           f"🔗 [Acheter](https://sorare.com/football/cards/{card['slug']})")
                    send_telegram_alert(msg)
                    st.session_state['sent_alerts'].add(card['slug'])

                if discount_pct > 0:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                        "Vente": formatted_time,
                        "_ts": timestamp,
                        "Joueur": card['anyPlayer']['displayName'],
                        "L15": l15,
                        "Cat": "🟢 In-Season" if is_in else "⚪ Classic",
                        "Prix (€)": p_now,
                        "Floor Actuel (€)": true_floor,
                        "Annonces": nb_market,
                        "Décote (%)": discount_pct
                    })
                    
        # On trie pour que la plus RECENTE soit en haut (Timestamp le plus grand)
        return sorted(findings, key=lambda x: x['_ts'], reverse=True)
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Nouveautés", layout="wide")

if st.session_state['token'] is None:
    st.title("🔐 Connexion Sorare")
    if not st.session_state['otp_needed']:
        if st.button("🚀 Initialiser via Secrets"):
            res = requests.get(f"https://api.sorare.com/api/v1/users/{DEFAULT_EMAIL}").json()
            salt = res.get("salt")
            if salt:
                hpwd = bcrypt.hashpw(DEFAULT_PWD.encode(), salt.encode()).decode()
                res_sign = sorare_sign_in(DEFAULT_EMAIL, hpwd)
                if res_sign.get('otpSessionChallenge'):
                    st.session_state['otp_needed'] = res_sign['otpSessionChallenge']
                    st.rerun()
                elif res_sign.get('jwtToken'):
                    st.session_state['token'] = res_sign['jwtToken']['token']
                    st.rerun()
    else:
        otp_code = st.text_input("Code 2FA :")
        if st.button("Valider OTP"):
            res_sign = sorare_sign_in(None, otp_attempt=otp_code, otp_challenge=st.session_state['otp_needed'])
            if res_sign.get('jwtToken'):
                st.session_state['token'] = res_sign['jwtToken']['token']
                st.session_state['otp_needed'] = None
                st.rerun()
else:
    st.sidebar.success(f"Radar Nouveautés Actif")
    st.sidebar.write(f"🕒 {datetime.now().strftime('%H:%M:%S')}")
    if st.sidebar.button("Déconnexion"):
        st.session_state.clear()
        st.rerun()

    data = scan_discount_flux(st.session_state['token'])
    if data:
        df = pd.DataFrame(data).drop(columns=['_ts']) # On cache le timestamp technique
        
        def style_df(row):
            styles = [''] * len(row)
            decote = row['Décote (%)']
            if decote >= 30: styles[8] = 'background-color: #28a745; color: white; font-weight: bold'
            elif decote >= 20: styles[8] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            elif decote >= 10: styles[8] = 'background-color: #fff3cd; color: #856404; font-weight: bold'
            return styles

        st.dataframe(
            df.style.apply(style_df, axis=1), 
            column_config={
                "🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir"),
                "L15": st.column_config.NumberColumn("L15", format="%d"),
                "Prix (€)": st.column_config.NumberColumn("Prix (€)", format="%.2f"),
                "Floor Actuel (€)": st.column_config.NumberColumn("Floor Actuel (€)", format="%.2f"),
                "Décote (%)": st.column_config.NumberColumn("Décote (%)", format="%.1f")
            }, 
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Attente de nouvelles mises en vente...")
    
    time.sleep(60)
    st.rerun()
