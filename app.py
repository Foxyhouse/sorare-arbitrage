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
    return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()

# --- RÉCUPÉRATION DU FLOOR LIMITED ---
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

# --- SCANNER DE MARCHÉ (FLUX RÉEL 24H) ---
def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On filtre pour n'avoir que ce qui a bougé depuis 24h
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
        st.session_state['last_json'] = res_json
        
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        findings = []
        for n in nodes:
            # On ignore les offres sans prix (échanges ou null)
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            if eur_cents is None: continue

            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            c = cards[0]
            # On ne garde que les RARES pour l'analyse
            if str(c.get('rarityTyped')).lower() == 'rare':
                findings.append({
                    "Mise en ligne": n.get('startDate'),
                    "Joueur": c.get('anyPlayer', {}).get('displayName'),
                    "Slug": c.get('anyPlayer', {}).get('slug'),
                    "Prix Rare (€)": float(eur_cents) / 100
                })
        
        # Tri chronologique (le plus récent en haut)
        findings = sorted(findings, key=lambda x: x['Mise en ligne'], reverse=True)

        # Calcul des ratios pour les Rares
        for item in findings[:15]: 
            item['Floor Limited (€)'] = get_limited_floor(item['Slug'], jwt_token)
            if item['Floor Limited (€)']:
                item['Ratio'] = round(item['Prix Rare (€)'] / item['Floor Limited (€)'], 2)
            else:
                item['Ratio'] = "N/A"
        
        return findings
    except Exception as e:
        st.error(f"Erreur de scan : {e}")
        return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Arbitrage Sorare Live", layout="wide")
st.title("⚽ Scanner d'Arbitrage (Flux 24h)")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    with st.form("login"):
        email = st.text_input("Email", value="jacques.troispoils@gmail.com")
        pwd = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Lancer le Scanner"):
            salt = get_user_salt(email)
            if salt:
                hpwd = bcrypt.hashpw(pwd.encode(), salt.encode()).decode()
                res = sorare_sign_in(email, hpwd)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
                else: st.error("Échec connexion.")
            else: st.error("Email inconnu.")
else:
    if st.sidebar.button("🔄 Rafraîchir le flux"): st.rerun()
    if st.sidebar.button("🚪 Déconnexion"):
        st.session_state['token'] = None
        st.rerun()

    with st.spinner("Analyse du marché live (dernières 24h)..."):
        data = scan_arbitrage_live(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data).drop(columns=['Slug'])
        
        def color_ratio(val):
            try:
                if float(val) < 4.0: return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''
        
        st.dataframe(df.style.applymap(color_ratio, subset=['Ratio']), use_container_width=True)
    else:
        st.warning("Aucune carte Rare détectée dans le flux récent. Réessaie dans un instant.")

    if st.checkbox("⚙️ Debug JSON Brut"):
        st.json(st.session_state.get('last_json', {}))
