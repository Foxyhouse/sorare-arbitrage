import streamlit as st
import requests
import bcrypt
import pandas as pd

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
    return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()

def get_limited_floor(player_slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query GetLim($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug, rarities: [limited], first: 1) {
          nodes { receiverSide { amounts { eurCents } } }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': player_slug}}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        if nodes:
            return float(nodes[0]['receiverSide']['amounts']['eurCents']) / 100
    except: pass
    return None

def scan_arbitrage_live(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    query = """
    query GetLiveFlux {
      tokens {
        liveSingleSaleOffers(first: 50, sport: FOOTBALL) {
          nodes {
            senderSide {
              anyCards {
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
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        rare_opportunities = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            card = cards[0]
            # On ne traite que les Rares [cite: 1023]
            if card.get('rarityTyped') == 'rare':
                player_name = card.get('anyPlayer', {}).get('displayName')
                player_slug = card.get('anyPlayer', {}).get('slug')
                rare_price = float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                
                # Check immédiat du floor Limited pour ce slug
                lim_floor = get_limited_floor(player_slug, jwt_token)
                
                ratio = rare_price / lim_floor if lim_floor else None
                
                rare_opportunities.append({
                    "Mis en ligne": n.get('startDate'),
                    "Joueur": player_name,
                    "Prix Rare (€)": rare_price,
                    "Floor Limited (€)": lim_floor,
                    "Ratio": round(ratio, 2) if ratio else "N/A",
                    "Slug": player_slug
                })
        return rare_opportunities
    except: return []

# --- UI ---
st.set_page_config(page_title="Arbitrage Scanner Live", layout="wide")
st.title("🔥 Scanner d'Arbitrage : Dernières Rares")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    # Bloc connexion (identique au précédent)
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Lancer le Scanner"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.sidebar.button("🔄 Rafraîchir le flux"): st.rerun()

    with st.spinner("Analyse des dernières pépites..."):
        data = scan_arbitrage_live(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data)
        # Style pour repérer les bonnes affaires
        def color_ratio(val):
            try:
                if float(val) < 4.0: return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''
            
        st.dataframe(df.style.applymap(color_ratio, subset=['Ratio']), use_container_width=True)
    else:
        st.info("Aucune carte Rare listée dans les 50 dernières annonces. Réessaie dans un instant.")
