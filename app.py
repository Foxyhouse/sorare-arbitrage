import streamlit as st
import requests
import bcrypt

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        if res.status_code == 200: return res.json().get("salt")
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
    except: return {"errors": [{"message": "Erreur connexion"}]}

# --- LOGIQUE DE SCANNER ---

def get_latest_rare_and_compare(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # 1. On récupère les 10 dernières offres Rares
    query_latest = """
    query GetLatestRares {
      tokens {
        liveSingleSaleOffers(rarities: [rare], first: 10) {
          nodes {
            senderSide {
              anyCards {
                slug
                player { displayName }
              }
            }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    
    try:
        res = requests.post(API_URL, json={'query': query_latest}, headers=headers).json()
        offers = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        results = []
        for offer in offers:
            card = offer.get('senderSide', {}).get('anyCards', [{}])[0]
            player_name = card.get('player', {}).get('displayName', "Inconnu")
            player_slug = card.get('slug').split('-')[0] # On simplifie pour avoir le slug joueur
            rare_price = float(offer.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
            
            # 2. Pour chaque offre, on cherche le floor Limited de ce joueur
            query_lim = """
            query GetLimFloor($slug: String!) {
              tokens {
                liveSingleSaleOffers(playerSlug: $slug, rarities: [limited]) {
                  nodes { receiverSide { amounts { eurCents } } }
                }
              }
            }
            """
            res_lim = requests.post(API_URL, json={'query': query_lim, 'variables': {'slug': player_slug}}, headers=headers).json()
            lim_offers = res_lim.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
            
            lim_prices = [float(o['receiverSide']['amounts']['eurCents'])/100 for o in lim_offers if o['receiverSide']['amounts']['eurCents']]
            min_lim = min(lim_prices) if lim_prices else None
            
            results.append({
                "name": player_name,
                "rare_price": rare_price,
                "lim_price": min_lim
            })
        return results
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Scanner Arbitrage", page_icon="🔥", layout="wide")
st.title("🔥 Scanner : 10 Dernières Ventes Rares")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    # (Garder ici ton bloc de connexion habituel...)
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Scanner le marché"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.button("🔄 Rafraîchir le flux"):
        st.rerun()

    data = get_latest_rare_and_compare(st.session_state['token'])
    
    for item in data:
        with st.container():
            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            c1.markdown(f"**{item['name']}**")
            c2.write(f"Rare: {item['rare_price']:.2f}€")
            
            if item['lim_price']:
                c3.write(f"Lim: {item['lim_price']:.2f}€")
                ratio = item['rare_price'] / item['lim_price']
                if ratio < 4.0:
                    c4.success(f"🎯 RATIO CHAUD : {ratio:.2f}")
                else:
                    c4.info(f"Ratio : {ratio:.2f}")
            else:
                c3.write("Pas de Lim")
                c4.write("-")
            st.divider()
