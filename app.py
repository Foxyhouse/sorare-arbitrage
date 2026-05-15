import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION (VERSION ROBUSTE) ---
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
        liveSingleSaleOffers(playerSlug: $slug, first: 10) {
          nodes {
            senderSide { anyCards { rarityTyped } }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        lim_prices = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards and cards[0].get('rarityTyped') == 'limited':
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
        liveSingleSaleOffers(first: 100, sport: FOOTBALL, updatedAfter: $since) {
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
        response = requests.post(API_URL, json={'query': query, 'variables': {'since': since_date}}, headers=headers)
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
        for item in findings[:15]: 
            item['Floor Limited (€)'] = get_limited_floor(item['Slug'], jwt_token)
            if item['Floor Limited (€)']:
                item['Ratio'] = round(item['Prix Rare (€)'] / item['Floor Limited (€)'], 2)
            else: item['Ratio'] = "N/A"
        return findings
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Scanner Arbitrage", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# GESTION CONNEXION
if not st.session_state['token']:
    with st.container():
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
                        else: st.error(f"Échec : {data.get('errors', [{'message': 'Inconnu'}])[0]['message']}")
                    else: st.error("Impossible de récupérer le sel.")
        else:
            with st.form("otp"):
                st.subheader("📱 Code 2FA")
                code = st.text_input("Saisir le code OTP")
                if st.form_submit_button("Valider"):
                    res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('jwtToken'):
                        st.session_state['token'] = data['jwtToken']['token']
                        st.rerun()
                    else: st.error("Code incorrect.")

# GESTION SCANNER
else:
    st.sidebar.success("✅ Connecté")
    if st.sidebar.button("Déconnexion"):
        st.session_state['token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()

    with st.spinner("Analyse du marché..."):
        data = scan_arbitrage_live(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data).drop(columns=['Slug'])
        def color_ratio(val):
            try:
                if float(val) < 4.0: return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''
        st.dataframe(df.style.applymap(color_ratio, subset=['Ratio']), use_container_width=True)
    else: st.warning("Aucune donnée.")
