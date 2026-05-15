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
    st.error("Erreur : Configurez vos secrets dans le dashboard Streamlit (TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SORARE_EMAIL, SORARE_PASSWORD)")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 
MIN_DISCOUNT_PERCENT = 20 # 🎯 Le filtre pour l'alerte Telegram (20%)

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
        errors { message }
      }
    }
    """
    variables = {"input": {"otpSessionChallenge": otp_challenge, "otpAttempt": otp_attempt}} if otp_challenge else {"input": {"email": email, "password": hashed_password}}
    try: return requests.post(API_URL, json={'query': query, 'variables': variables}, timeout=10).json().get('data', {}).get('signIn', {})
    except: return {}

# --- FONCTION : MOYENNE DES 5 DERNIÈRES VENTES (LIMITED) ---
def get_last_5_average(player_slug, is_in_season, rarity_typed, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetPastSales($slug: String!) {
      tokens {
        past_offers: allSingleSaleOffers(playerSlug: $slug, states: [SUCCESS], first: 50) {
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
        nodes = res.get('data', {}).get('tokens', {}).get('past_offers', {}).get('nodes', [])
        
        valid_prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            card = cards[0]
            
            card_is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
            # Filtre strict : Même rareté (limited) ET même catégorie (In-Season / Classic)
            if card['rarityTyped'] == rarity_typed and card_is_in_season == is_in_season:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    valid_prices.append(round(float(eur) / 100, 2))
            
            # On s'arrête dès qu'on a nos 5 dernières ventes
            if len(valid_prices) == 5:
                break
                
        if len(valid_prices) > 0:
            avg = sum(valid_prices) / len(valid_prices)
            return round(avg, 2), len(valid_prices)
        return None, 0
    except: return None, 0

# --- SCANNER DE DÉCOTE (LIMITED) ---
def scan_discount_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFlux {
      tokens {
        liveSingleSaleOffers(first: 150, sport: FOOTBALL) {
          nodes {
            senderSide { anyCards { slug rarityTyped seasonYear anyPlayer { displayName slug } } }
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
            
            # Ciblage exclusif des LIMITED
            if eur and cards and cards[0]['rarityTyped'] == 'limited':
                card = cards[0]
                is_in = (card['seasonYear'] == CURRENT_SEASON_YEAR)
                p_now = round(float(eur) / 100, 2)
                
                # Calcul de la moyenne des ventes passées
                avg_price, nb_sales = get_last_5_average(card['anyPlayer']['slug'], is_in, 'limited', jwt_token)
                
                discount_pct = 0
                if avg_price and avg_price > 0:
                    discount_pct = round(((avg_price - p_now) / avg_price) * 100, 1)
                
                # Formatage de l'heure UTC vers l'heure locale
                raw_date = n.get('startDate', "")
                try:
                    utc_dt = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.tzutc())
                    formatted_time = utc_dt.astimezone(tz.tzlocal()).strftime("%H:%M:%S")
                except: formatted_time = raw_date

                # Alerte Telegram
                if discount_pct >= MIN_DISCOUNT_PERCENT and nb_sales >= 2 and card['slug'] not in st.session_state['sent_alerts']:
                    msg = (f"🟨 *GROSSE DÉCOTE LIMITED : -{discount_pct}%*\n\n"
                           f"👤 {card['anyPlayer']['displayName']}\n"
                           f"💰 Prix Listé : {p_now}€\n"
                           f"📉 Moyenne ({nb_sales}V) : {avg_price}€\n"
                           f"🔗 [Acheter sur Sorare](https://sorare.com/football/cards/{card['slug']})")
                    send_telegram_alert(msg)
                    st.session_state['sent_alerts'].add(card['slug'])

                # Ajout au tableau (Uniquement si le prix est inférieur à la moyenne)
                if discount_pct > 0:
                    findings.append({
                        "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                        "Vente": formatted_time,
                        "Joueur": card['anyPlayer']['displayName'],
                        "Cat": "🟢 In-Season" if is_in else "⚪ Classic",
                        "Prix (€)": p_now,
                        "Moyenne 5V (€)": avg_price,
                        "Vol": f"{nb_sales}/5",
                        "Décote (%)": discount_pct
                    })
                    
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- INTERFACE STRICTE ---
st.set_page_config(page_title="Sniper Vraie Valeur (Limited)", layout="wide")

# CAS 1 : Connexion
if st.session_state['token'] is None:
    st.title("🔐 Connexion Sorare")
    if not st.session_state['otp_needed']:
        if st.button("🚀 Se connecter via Secrets"):
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
            else: st.error("Email inconnu.")
    else:
        otp_code = st.text_input("Code 2FA :", key="otp_input")
        if st.button("Valider OTP"):
            res_sign = sorare_sign_in(None, otp_attempt=otp_code, otp_challenge=st.session_state['otp_needed'])
            if res_sign.get('jwtToken'):
                st.session_state['token'] = res_sign['jwtToken']['token']
                st.session_state['otp_needed'] = None
                st.rerun()
            else: st.error("OTP Invalide.")

# CAS 2 : Scanner Actif
else:
    st.sidebar.success(f"Scanner Limited Actif\n(Cible Telegram: -{MIN_DISCOUNT_PERCENT}%)")
    st.sidebar.write(f"🕒 Dernière màj : {datetime.now().strftime('%H:%M:%S')}")
    if st.sidebar.button("Déconnexion"):
        st.session_state.clear()
        st.rerun()

    data = scan_discount_flux(st.session_state['token'])
    if data:
        df = pd.DataFrame(data)
        
        # Coloration : Ligne verte si la décote dépasse la cible configurée
        def style_df(row):
            styles = [''] * len(row)
            if row['Décote (%)'] >= MIN_DISCOUNT_PERCENT:
                styles[7] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            return styles

        st.dataframe(
            df.style.apply(style_df, axis=1), 
            column_config={"🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir")}, 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("Recherche de cartes sous-évaluées...")
    
    # Auto-Refresh
    time.sleep(60)
    st.rerun()
