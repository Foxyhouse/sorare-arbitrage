import streamlit as st
import requests
import bcrypt
import pandas as pd
from datetime import datetime, timedelta

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION (Identique à votre version fonctionnelle) ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        if res.status_code == 200:
            return res.json().get("salt")
    except: return None
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
        res = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, timeout=10)
        return res.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

# --- LOGIQUE DE MARCHÉ ---
def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, first: 5) {
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
        lim_prices = [float(n['receiverSide']['amounts']['eurCents'])/100 for n in nodes]
        return min(lim_prices) if lim_prices else None
    except: return None

def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    since_date = (datetime.now() - timedelta(hours=24)).isoformat() + "Z"
    query = """
    query GetLiveFlux($since: ISO8601DateTime) {
      tokens {
        liveSingleSaleOffers(first: 50, sport: FOOTBALL, updatedAfter: $since) {
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
        res = requests.post(API_URL, json={'query': query, 'variables': {'since': since_date}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingle_SaleOffers', {}).get('nodes', [])
        findings = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards and str(cards[0].get('rarityTyped')).lower() == 'rare':
                # Formatage de la date de mise en vente
                raw_date = n.get('startDate')
                formatted_date = ""
                if raw_date:
                    dt = datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                    formatted_date = dt.strftime("%d/%m %H:%M") # Format: 15/05 14:30

                findings.append({
                    "Mise en vente": formatted_date,
                    "Joueur": cards[0].get('anyPlayer', {}).get('displayName'),
                    "Slug": cards[0].get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(n['receiverSide']['amounts']['eurCents']) / 100
                })
        
        # Scan des prix Limited pour les 10 premières opportunités
        for item in findings[:10]:
            floor = get_limited_floor(item['Slug'], jwt_token)
            item['Floor Limited (€)'] = floor
            item['Ratio'] = round(item['Prix Rare (€)'] / floor, 2) if floor else None
        return findings
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Arbitrage Sorare 2026", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None

# ... (Le bloc d'authentification reste le même) ...

if st.session_state['token']:
    if st.button("🔄 Rafraîchir le flux"):
        st.rerun()

    with st.spinner("Analyse des dernières ventes..."):
        results = scan_arbitrage_live(st.session_state['token'])
    
    if results:
        df = pd.DataFrame(results).drop(columns=['Slug'])
        
        # Style pour le Ratio (Pandas 2.x compatible)
        def color_ratio(val):
            try:
                if val is not None and float(val) < 4.0:
                    return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''

        # Affichage avec la colonne "Mise en vente" ajoutée
        styled_df = df.style.map(color_ratio, subset=['Ratio'])
        st.dataframe(styled_df, use_container_width=True)
