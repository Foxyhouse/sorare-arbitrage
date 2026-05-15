import streamlit as st
import requests
import bcrypt
import pandas as pd
import time
from datetime import datetime

# --- CONFIGURATION ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"
CURRENT_SEASON_YEAR = 2026 

# --- FONCTIONS AUTH ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        return res.json().get("salt") if res.status_code == 200 else None
    except: return None

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") { token }
        otpSessionChallenge
        errors { message }
      }
    }
    """
    input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt} if otp_session_challenge else {"email": email, "password": hashed_password}
    try:
        return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, timeout=10).json()
    except: return {"errors": [{"message": "Erreur serveur"}]}

# --- FONCTIONS SCAN (SEGMENTÉES) ---
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
        lim_prices, rare_prices = [], []
        for n in nodes:
            card = n['senderSide']['anyCards'][0]
            card_is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
            if card_is_in_season == is_in_season:
                eur = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if eur:
                    p = float(eur) / 100
                    if card['rarityTyped'] == 'limited': lim_prices.append(p)
                    if card['rarityTyped'] == 'rare': rare_prices.append(p)
        return (min(lim_prices) if lim_prices else None), (min(rare_prices) if rare_prices else None)
    except: return None, None

def scan_arbitrage_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 100, sport: FOOTBALL) {
          nodes {
            senderSide { 
              anyCards { slug rarityTyped seasonYear anyPlayer { displayName slug } } 
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        if "errors" in res: return [], "Session expirée"
        
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            cards = n.get('senderSide', {}).get('anyCards', [])
            if eur_cents and cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                card = cards[0]
                is_in_season = (card.get('seasonYear') == CURRENT_SEASON_YEAR)
                p_now = round(float(eur_cents) / 100, 2)
                f_lim, f_rare = get_segmented_floors(card['anyPlayer']['slug'], is_in_season, jwt_token)
                findings.append({
                    "🛒": f"https://sorare.com/football/cards/{card['slug']}",
                    "Vente": n.get('startDate'),
                    "Joueur": card['anyPlayer']['displayName'],
                    "Catégorie": "🟢 In-Season" if is_in_season else "⚪ Classic",
                    "Prix (€)": p_now,
                    "Floor Rare (€)": round(f_rare, 2) if f_rare else None,
                    "Floor Lim (€)": round(f_lim, 2) if f_lim else None,
                    "Ratio": round(p_now / f_lim, 2) if f_lim else None
                })
        return sorted(findings, key=lambda x: x['Vente'], reverse=True), None
    except: return [], "Erreur"

# --- INTERFACE ---
st.set_page_config(page_title="Sniper Arbitrage", layout="wide")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# BLOC CONNEXION
if not st.session_state['token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.title("🔑 Connexion Sorare")
            u_email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            u_pwd = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Lancer le Scanner"):
                salt = get_user_salt(u_email)
                if salt:
                    hpwd = bcrypt.hashpw(u_pwd.encode(), salt.encode()).decode()
                    res = sorare_sign_in(u_email, hpwd)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'] = data['otpSessionChallenge']
                        st.session_state['temp_email'] = u_email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['token'] = data['jwtToken']['token']
                        st.rerun()
                    else: st.error("Identifiants incorrects.")
                else: st.error("Compte introuvable.")
    else:
        with st.form("otp"):
            st.title("📱 Code 2FA Requis")
            code = st.text_input("Saisir le code OTP")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
                else: st.error("Code invalide.")

# BLOC SCANNER
else:
    st.title("🎯 Arbitrage Live (Auto-Refresh 60s)")
    st.sidebar.markdown(f"🕒 **Dernier scan :** {datetime.now().strftime('%H:%M:%S')}")
    if st.sidebar.button("🚪 Déconnexion"):
        st.session_state.clear()
        st.rerun()

    data, err = scan_arbitrage_flux(st.session_state['token'])
    
    if err == "Session expirée":
        st.session_state['token'] = None
        st.rerun()
    elif data:
        df = pd.DataFrame(data)
        def style_df(row):
            styles = [''] * len(row)
            if row['Ratio'] and float(row['Ratio']) < 4.0: styles[7] = 'background-color: #d4edda; color: #155724; font-weight: bold'
            if row['Floor Rare (€)'] and row['Prix (€)'] <= row['Floor Rare (€)']: styles[4] = 'background-color: #fff3cd; color: #856404;'
            return styles

        st.dataframe(df.style.apply(style_df, axis=1), 
                     column_config={"🛒": st.column_config.LinkColumn("🛒", display_text="Acheter")},
                     use_container_width=True, hide_index=True)
    else:
        st.info("Recherche de Rares...")

    time.sleep(60)
    st.rerun()
