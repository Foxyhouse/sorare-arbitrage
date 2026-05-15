import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

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

def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 5) {
          nodes { receiverSide { amounts { eurCents } } }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        # Sécurité : On filtre uniquement les offres qui ont un prix non nul
        prices = [float(n['receiverSide']['amounts']['eurCents'])/100 for n in nodes if n.get('receiverSide', {}).get('amounts') and n['receiverSide']['amounts'].get('eurCents')]
        return min(prices) if prices else None
    except: return None

def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    since_date = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    query = """
    query GetLiveFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 50, sport: FOOTBALL, updatedAfter: $since) {
          nodes {
            senderSide { anyCards { rarityTyped anyPlayer { displayName slug } } }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'since': since_date}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        findings = []
        for n in nodes:
            # SÉCURITÉ : On vérifie que le prix existe avant de continuer
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if eur_cents is None:
                continue

            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                raw_date = n.get('startDate', "")
                try:
                    f_date = datetime.fromisoformat(raw_date.replace('Z', '+00:00')).strftime("%H:%M")
                except:
                    f_date = "--:--"
                
                findings.append({
                    "Vente": f_date,
                    "Joueur": cards[0].get('anyPlayer', {}).get('displayName'),
                    "Slug": cards[0].get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(eur_cents) / 100
                })
        
        # On calcule le ratio pour les Rares trouvées
        for item in findings[:15]:
            floor = get_limited_floor(item['Slug'], jwt_token)
            item['Floor Limited (€)'] = floor
            if floor and floor > 0:
                item['Ratio'] = round(item['Prix Rare (€)'] / floor, 2)
            else:
                item['Ratio'] = None
        return findings
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Scanner Arbitrage", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
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
            code = st.text_input("Code OTP")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    st.sidebar.button("Déconnexion", on_click=lambda: st.session_state.clear())
    if st.button("🔄 Rafraîchir le flux"):
        st.rerun()

    results = scan_arbitrage_live(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        def color_ratio(val):
            try:
                if val is not None and float(val) < 4.0:
                    return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''

        st.dataframe(df.style.map(color_ratio, subset=['Ratio']), use_container_width=True)
    else:
        st.info("Aucune Rare avec prix détectée. Réessaie.")
