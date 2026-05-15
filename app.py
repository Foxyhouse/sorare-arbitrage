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
        prices = [float(n['receiverSide']['amounts']['eurCents'])/100 for n in nodes if n.get('receiverSide', {}).get('amounts')]
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
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                # Sécurité sur la date
                raw_date = n.get('startDate', "")
                try:
                    f_date = datetime.fromisoformat(raw_date.replace('Z', '+00:00')).strftime("%H:%M")
                except:
                    f_date = "--:--"
                
                findings.append({
                    "Vente": f_date,
                    "Joueur": cards[0].get('anyPlayer', {}).get('displayName'),
                    "Slug": cards[0].get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(n['receiverSide']['amounts']['eurCents']) / 100
                })
        
        for item in findings[:10]:
            floor = get_limited_floor(item['Slug'], jwt_token)
            item['Floor Limited (€)'] = floor
            item['Ratio'] = round(item['Prix Rare (€)'] / floor, 2) if floor else None
        return findings
    except Exception as e:
        st.error(f"Erreur technique : {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Arbitrage Sorare 2026", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None

# ... (Mettre ici le bloc de connexion que tu utilisais, il fonctionne très bien) ...

if st.session_state['token']:
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
        st.info("Recherche de Rares en cours...")
