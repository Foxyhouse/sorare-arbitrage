import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        if res.status_code == 200:
            return res.json().get("salt")
    except:
        return None
    return None

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
    if otp_session_challenge:
        input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt}
    else:
        input_data = {"email": email, "password": hashed_password}
        
    try:
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        res = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

# --- LOGIQUE DE MARCHÉ ---
def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 15) {
          nodes {
            senderSide { anyCards { rarityTyped } }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers, timeout=10).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        lim_prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards and str(cards[0].get('rarityTyped')).lower() == 'limited':
                price = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
                if price: lim_prices.append(float(price) / 100)
        return min(lim_prices) if lim_prices else None
    except: return None

def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    since_date = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    query = """
    query GetLiveFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 80, sport: FOOTBALL, updatedAfter: $since) {
          nodes {
            senderSide {
              anyCards {
                slug
                rarityTyped
                anyPlayer { displayName slug }
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
        response = requests.post(API_URL, json={'query': query, 'variables': {'since': since_date}}, headers=headers, timeout=15)
        res_json = response.json()
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        for n in nodes:
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if eur_cents is None: continue
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            c = cards[0]
            if str(c.get('rarityTyped')).lower() == 'rare':
                findings.append({
                    "Mise en ligne": n.get('startDate'),
                    "Joueur": c.get('anyPlayer', {}).get('displayName'),
                    "Slug": c.get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(eur_cents) / 100
                })
        
        findings = sorted(findings, key=lambda x: x['Mise en ligne'], reverse=True)
        
        # On limite le scan Limited pour éviter les timeouts
        for item in findings[:12]: 
            floor = get_limited_floor(item['Slug'], jwt_token)
            item['Floor Limited (€)'] = floor
            if floor and floor > 0:
                item['Ratio'] = round(item['Prix Rare (€)'] / floor, 2)
            else: 
                item['Ratio'] = None
        return findings
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Arbitrage Sorare 2026", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['token']:
    # Bloc Login (Inchangé)
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.subheader("🔑 Connexion")
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
                    else: st.error("Erreur d'identifiants.")
                else: st.error("Utilisateur introuvable.")
    else:
        with st.form("otp"):
            code = st.text_input("Code OTP")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()

else:
    st.sidebar.button("🚪 Déconnexion", on_click=lambda: st.session_state.clear())
    
    if st.button("🔄 Rafraîchir le flux"):
        st.rerun()

    with st.spinner("Analyse du marché..."):
        results = scan_arbitrage_live(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        
        # --- CORRECTION DU STYLE ( Pandas 2.x ) ---
        def color_ratio(val):
            try:
                # On ne colorie que si c'est un nombre et < 4.0
                if val is not None and float(val) < 4.0:
                    return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except:
                pass
            return ''

        # Utilisation de .map() au lieu de .applymap() pour la compatibilité
        styled_df = df.style.map(color_ratio, subset=['Ratio'])
        
        st.dataframe(styled_df, use_container_width=True)
    else:
        st.warning("Aucune Rare trouvée dans le flux actuel.")
