import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION BLINDÉE ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
        if res.status_code == 200: return res.json().get("salt")
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
    input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt} if otp_session_challenge else {"email": email, "password": hashed_password}
    try:
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers).json()
    except Exception as e: return {"errors": [{"message": str(e)}]}

# --- RÉCUPÉRATION DES PRIX (La réponse soufflée par l'API) ---
def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # ON UTILISE EXACTEMENT CE QUE L'API A SUGGÉRÉ : anyCards
    query = """
    query GetFloor($slugs: [String!]) {
      anyCards(playerSlugs: $slugs, rarities: [limited, rare], first: 100) {
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
        
        if "errors" in res: return None, None

        # On n'oublie pas de changer ici aussi
        nodes = res.get('data', {}).get('anyCards', {}).get('nodes', [])
        
        lim_prices, rare_prices = [], []
        
        for n in nodes:
            offer = n.get('liveSingleSaleOffer') or n.get('token', {}).get('liveSingleSaleOffer')
            if offer and offer.get('priceInFiat') and offer['priceInFiat'].get('eur'):
                val = float(offer['priceInFiat']['eur'])
                rarity = n.get('rarity')
                if rarity == 'limited': lim_prices.append(val)
                elif rarity == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None)
    except: return None, None

# --- INTERFACE UTILISATEUR ---
st.set_page_config(page_title="Sorare Arbitrage Tool", page_icon="🎯")
st.title("🎯 Sorare Arbitrage Real-Time")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.subheader("🔑 Connexion")
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter"):
                salt = get_user_salt(email)
                if salt:
                    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt.encode('utf-8')).decode('utf-8')
                    res = sorare_sign_in(email, hashed_password=hashed_pw)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'], st.session_state['temp_email'] = data['otpSessionChallenge'], email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
                    else: st.error(f"Erreur API : {data.get('errors', [{}])[0].get('message', 'Erreur de connexion.')}")
                else: st.error("Impossible de récupérer le sel du compte.")
    else:
        with st.form("otp"):
            st.subheader("📱 Code 2FA")
            otp_code = st.text_input("Saisir le code à 6 chiffres")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['final_token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
                else: st.error("Code incorrect.")

else:
    st.success("✅ Connecté au marché Sorare")
    with st.sidebar:
        st.write(f"Session active : {st.session_state.get('temp_email', 'Utilisateur')}")
        if st.button("Se déconnecter"):
            st.session_state['final_token'] = None
            st.session_state['otp_challenge'] = None
            st.rerun()
    
    st.subheader("🔍 Monitoring des opportunités")
    watchlist = {"Hervé Koffi": "kouakou-herve-koffi", "Jordan Lefort": "jordan-lefort"}

    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            col2.write(f"L: {p_lim}€")
            col3.write(f"R: {p_rare}€")
            if ratio < 4.0: col4.success(f"🔥 Ratio: {ratio:.2f} (BUY !)")
            else: col4.info(f"⚖️ Ratio: {ratio:.2f}")
        else: col4.warning("Aucun prix trouvé sur le marché.")
        st.divider()

    if st.checkbox("Afficher Debug JSON"):
        st.json(st.session_state.get('last_debug', {}))
