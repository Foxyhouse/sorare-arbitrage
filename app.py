import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURATION (SECRETS) ---
try:
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["TELEGRAM_CHAT_ID"]
    DEFAULT_EMAIL = st.secrets["SORARE_EMAIL"]
    DEFAULT_PWD = st.secrets["SORARE_PASSWORD"]
except:
    st.error("Erreur Secrets : TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, SORARE_EMAIL, SORARE_PASSWORD manquants.")
    st.stop()

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

# --- ÉTAT DE LA SESSION ---
if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_needed' not in st.session_state: st.session_state['otp_needed'] = None
if 'sent_alerts' not in st.session_state: st.session_state['sent_alerts'] = set()

# --- FONCTIONS ---
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
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': variables}, timeout=10).json()
        return res.get('data', {}).get('signIn', {})
    except: return {}

def get_segmented_floors(player_slug, is_in_season, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetSegFloors($slug: String!) {
      tokens {
        all_offers: liveSingleSaleOffers(playerSlug: $slug, first: 40) {
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
        lim_p, rare_p = [], []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            if (card.get('seasonYear') == CURRENT_SEASON_YEAR) == is_in_season:
                eur = n['receiverSide']['amounts']['eurCents']
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_p.append(p)
                    elif card['rarityTyped'] == 'rare': rare_p.append(p)
        return min(lim_p) if lim_p else None, min(rare_p) if rare_p else None
    except: return None, None

def scan_and_alert(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetFlux {
      tokens {
        liveSingleSaleOffers(first: 80, sport: FOOTBALL) {
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
            if eur and cards and cards[0]['rarityTyped'] == 'rare':
                card = cards[0]
                is_in = (card['seasonYear'] == CURRENT_SEASON_YEAR)
                p_now = round(float(eur) / 100, 2)
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in, jwt_token)
                ratio = round(p_now / f_lim, 2) if f_lim else 99
                
                # Alerte Telegram
                if ratio < 1.5 and card['slug'] not in st.session_state['sent_alerts']:
                    send_telegram_alert(f"🚀 *PÉPITE !* {card['anyPlayer']['displayName']} à {p_now}€ (Ratio: {ratio})\n[Lien](https://sorare.com/football/cards/{card['slug']})")
                    st.session_state['sent_alerts'].add(card['slug'])

                # Ajout au tableau complet
                findings.append({
                    "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                    "Vente": n['startDate'],
                    "Joueur": card['anyPlayer']['displayName'],
                    "Catégorie": "🟢 In-Season" if is_in else "⚪ Classic",
                    "Prix (€)": p_now,
                    "Floor Rare (€)": f_rare,
                    "Floor Lim (€)": f_lim,
                    "Ratio": ratio if ratio != 99 else None
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True)
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Pro 2026", layout="wide")

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

# CAS 2 : Connecté -> Scanner + Auto-refresh
else:
    st.sidebar.success("Scanner Actif")
    st.sidebar.write(f"🕒 Dernière màj : {datetime.now().strftime('%H:%M:%S')}")
    if st.sidebar.button("Déconnexion"):
        st.session_state.clear()
        st.rerun()

    data = scan_and_alert(st.session_state['token'])
    if data:
        df = pd.DataFrame(data)
        
        # --- RETOUR DU DESIGN ---
        def style_df(row):
            styles = [''] * len(row)
            # Vert si ratio < 4.0 (Colonne 7 = Ratio)
            if row['Ratio'] is not None and float(row['Ratio']) < 4.0:
                styles[7] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            # Jaune/Orange si Undercut (Colonne 4 = Prix)
            if row['Floor Rare (€)'] is not None and row['Prix (€)'] <= row['Floor Rare (€)']:
                styles[4] = 'background-color: #fff3cd; color: #856404; font-weight: bold'
            return styles

        st.dataframe(
            df.style.apply(style_df, axis=1), 
            column_config={"🛒": st.column_config.LinkColumn("Lien", display_text="Ouvrir")}, 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("Recherche de pépites...")
    
    # Auto-refresh de 60 secondes
    time.sleep(60)
    st.rerun()
