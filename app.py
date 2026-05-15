import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- 1. AUTHENTIFICATION (RESTAURÉE À LA VERSION FONCTIONNELLE) ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
        if res.status_code == 200:
            return res.json().get("salt")
    except:
        return None
    return None

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") {
          token
        }
        otpSessionChallenge
        errors { message }
      }
    }
    """
    if otp_session_challenge:
        input_data = {
            "otpSessionChallenge": otp_session_challenge,
            "otpAttempt": otp_attempt
        }
    else:
        input_data = {
            "email": email,
            "password": hashed_password
        }

    try:
        # LE HEADER CRITIQUE QUI AVAIT DISPARU EST DE RETOUR
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers)
        return response.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

# --- 2. RÉCUPÉRATION DES PRIX (allCards) ---
def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    query = """
    query GetFloor($slugs: [String!]) {
      allCards(playerSlugs: $slugs, rarities: [limited, rare], first: 100) {
        nodes {
          rarity
          liveSingleSaleOffer {
            priceInFiat { eur }
          }
          token {
            liveSingleSaleOffer {
              priceInFiat { eur }
            }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slugs': [slug]}}, headers=headers).json()
        st.session_state['last_debug'] = res 
        
        if "errors" in res:
            return None, None

        nodes = res.get('data', {}).get('allCards', {}).get('nodes', [])
        
        lim_prices, rare_prices = [], []
        
        for n in nodes:
            offer = n.get('liveSingleSaleOffer') or n.get('token', {}).get('liveSingleSaleOffer')
            if offer and offer.get('priceInFiat') and offer['priceInFiat'].get('eur'):
                val = float(offer['priceInFiat']['eur'])
                rarity = n.get('rarity')
                
                if rarity == 'limited': lim_prices.append(val)
                elif rarity == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, 
                min(rare_prices) if rare_prices else None)
    except:
        return None, None

# --- 3. INTERFACE UTILISATEUR ---
st.set_page_config(page_title="Sorare Arbitrage Tool", page_icon="📈")
st.title("📈 Sorare Arbitrage Real-Time")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.subheader("🔑 Connexion")
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter"):
