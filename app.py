import streamlit as st
import requests
import bcrypt

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

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
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers).json()
    except: return {"errors": [{"message": "Erreur de connexion"}]}

def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # LA REQUÊTE OFFICIELLE (validée par le schéma fourni)
    # On passe par n'importe quel joueur pour lister ses cartes avec anyCards
    query = """
    query GetFloor($slug: String!) {
      anyPlayer(slug: $slug) {
        anyCards(rarities: [limited, rare]) {
          nodes {
            rarityTyped
            liveSingleSaleOffer {
              receiverSide {
                amounts {
                  wei
                }
              }
            }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers).json()
        st.session_state['last_debug'] = res 
        
        if "errors" in res: return None, None

        # Accès selon la hiérarchie du schéma [cite: 36, 39, 1423, 1425]
        player_data = res.get('data', {}).get('anyPlayer')
        if not player_data: return None, None
        
        cards = player_data.get('anyCards', {}).get('nodes', [])
        lim_prices, rare_prices = [], []
        
        for c in cards:
            offer = c.get('liveSingleSaleOffer')
            if offer:
                receiver = offer.get('receiverSide', {})
                # Le schéma précise receiverSide -> amounts -> wei 
                wei_val = receiver.get('amounts', {}).get('wei')
                if wei_val:
                    val_eth = float(wei_val) / 1e18
                    rarity = str(c.get('rarityTyped')).lower()
                    if rarity == 'limited': lim_prices.append(val_eth)
                    elif rarity == 'rare': rare_prices.append(val_eth)
        
        return (min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None)
    except: return None, None

# --- INTERFACE ---
st.set_page_config(page_title="Sorare Arbitrage Tool", page_icon="🎯")
st.title("🎯 Arbitrage Limited / Rare")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp' not in st.session_state: st.session_state['otp'] = None

if not st.session_state['token']:
    if not st.session_state['otp']:
        with st.form("login"):
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            pwd = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Connexion"):
                salt = get_user_salt(email)
                if salt:
                    hpwd = bcrypt.hashpw(pwd.encode(), salt.encode()).decode()
                    res = sorare_sign_in(email, hpwd)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp'], st.session_state['mail'] = data['otpSessionChallenge'], email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['token'] = data['jwtToken']['token']
                        st.rerun()
    else:
        with st.form("2fa"):
            code = st.text_input("Code 2FA")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['mail'], otp_attempt=code, otp_session_challenge=st.session_state['otp'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    watchlist = {"Hervé Koffi": "kouakou-herve-koffi", "Jordan Lefort": "jordan-lefort"}
    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['token'])
        col1, col2, col3, col4 = st.columns([2,1,1,2])
        col1.write(f"**{name}**")
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            col2.write(f"L: {p_lim:.4f} Ξ")
            col3.write(f"R: {p_rare:.4f} Ξ")
            if ratio < 4.0: col4.success(f"🔥 Ratio: {ratio:.2f}")
            else: col4.info(f"Ratio: {ratio:.2f}")
        else: col4.warning("Pas d'offres")
        st.divider()
    if st.checkbox("Debug JSON"): st.json(st.session_state.get('last_debug'))
