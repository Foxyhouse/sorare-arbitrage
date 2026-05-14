import streamlit as st
import requests
import bcrypt

# Configuration
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- FONCTIONS TECHNIQUES ---

def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
        return res.json().get("salt") if res.status_code == 200 else None
    except: return None

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "%s") { token }
        otpSessionChallenge
        errors { message }
      }
    }
    """ % AUDIENCE
    if otp_session_challenge:
        input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt}
    else:
        input_data = {"email": email, "password": hashed_password}
    try:
        return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()
    except Exception as e: return {"errors": [{"message": str(e)}]}

def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # LA REQUÊTE CIBLE : On va chercher dans le marché des tokens
    query = """
    query GetMarketFloor($slug: String!) {
      tokenMarket {
        fixedPriceListings(playerSlugs: [$slug], rarities: [limited, rare]) {
          nodes {
            price { eur }
            token { rarity }
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers)
        res_json = response.json()
        st.session_state['last_debug'] = res_json 
        
        if "errors" in res_json: return None, None

        listings = res_json.get('data', {}).get('tokenMarket', {}).get('fixedPriceListings', {}).get('nodes', [])
        
        lim_prices = []
        rare_prices = []
        
        for item in listings:
            p = item.get('price', {}).get('eur')
            r = item.get('token', {}).get('rarity')
            if p and r:
                val = float(p)
                if r == 'limited': lim_prices.append(val)
                elif r == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, 
                min(rare_prices) if rare_prices else None)
    except:
        return None, None

# --- INTERFACE ---

st.set_page_config(page_title="Sorare Arbitrage", page_icon="💹")
st.title("💹 Sorare Arbitrage v2026")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# AUTHENTIFICATION
if not st.session_state['final_token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Connexion"):
                salt = get_user_salt(email)
                if salt:
                    hpw = bcrypt.hashpw(password.encode(), salt.encode()).decode()
                    res = sorare_sign_in(email, hashed_password=hpw)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'], st.session_state['temp_email'] = data['otpSessionChallenge'], email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
    else:
        with st.form("otp"):
            code = st.text_input("Code 2FA")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['final_token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()

# DASHBOARD
else:
    st.sidebar.success("Connecté !")
    if st.sidebar.button("Déconnexion"):
        st.session_state['final_token'] = None
        st.rerun()
    
    debug_mode = st.sidebar.checkbox("Afficher Debug JSON")
    
    watchlist = {
        "Hervé Koffi": "kouakou-herve-koffi",
        "Jordan Lefort": "jordan-lefort"
    }

    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            col2.write(f"{p_lim}€")
            col3.write(f"{p_rare}€")
            if ratio < 4: col4.success(f"Ratio: {ratio:.2f} 🔥")
            else: col4.info(f"Ratio: {ratio:.2f}")
        else:
            col4.warning("Aucune vente directe")
        st.divider()

    if debug_mode and 'last_debug' in st.session_state:
        st.json(st.session_state['last_debug'])
