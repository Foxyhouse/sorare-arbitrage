import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION ---
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
    input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt} if otp_session_challenge else {"email": email, "password": hashed_password}
    return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()

# --- RÉCUPÉRATION DES PRIX (LA VRAIE REQUÊTE !) ---
def get_market_data(slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # LA VRAIE RACINE : 'allCards' (Issue #156 sur le GitHub Sorare)
    # On limite à 'first: 100' pour éviter les rejets pour complexité (limite de l'API)
    query = """
    query GetFloor($slugs: [String!]) {
      allCards(playerSlugs: $slugs, rarities: [limited, rare], first: 100) {
        nodes {
          rarity
          # Cas A : Le prix est directement sur la carte
          liveSingleSaleOffer {
            priceInFiat { eur }
          }
          # Cas B : Le prix est rangé dans l'objet 'token' de la carte
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
            # Sécurité : On cherche l'offre de vente dans l'un ou l'autre des champs
            offer = n.get('liveSingleSaleOffer') or n.get('token', {}).get('liveSingleSaleOffer')
            
            # Si l'offre existe et a un prix en euros
            if offer and offer.get('priceInFiat') and offer['priceInFiat'].get('eur'):
                val = float(offer['priceInFiat']['eur'])
                rarity = n.get('rarity')
                
                if rarity == 'limited': lim_prices.append(val)
                elif rarity == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, 
                min(rare_prices) if rare_prices else None)
    except:
        return None, None

# --- INTERFACE ---
st.set_page_config(page_title="Sorare Arbitrage Final", page_icon="🏆")
st.title("🏆 Sorare Arbitrage (Version Validée)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    with st.form("login"):
        u_email = st.text_input("Email", value="jacques.troispoils@gmail.com")
        u_pass = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            salt = get_user_salt(u_email)
            if salt:
                hpw = bcrypt.hashpw(u_pass.encode(), salt.encode()).decode()
                res = sorare_sign_in(u_email, hashed_password=hpw)
                d = res.get('data', {}).get('signIn', {})
                if d.get('otpSessionChallenge'):
                    st.session_state['otp_challenge'], st.session_state['temp_email'] = d['otpSessionChallenge'], u_email
                    st.rerun()
                elif d.get('jwtToken'):
                    st.session_state['final_token'] = d['jwtToken']['token']
                    st.rerun()
else:
    st.sidebar.success("Connecté !")
    if st.sidebar.button("Déconnexion"):
        st.session_state['final_token'] = None
        st.rerun()

    st.subheader("📊 Tableau de Chasse")
    watchlist = {"Hervé Koffi": "kouakou-herve-koffi", "Jordan Lefort": "jordan-lefort"}
    
    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        
        if p_lim: col2.metric("Limited", f"{p_lim}€")
        if p_rare: col3.metric("Rare", f"{p_rare}€")
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            if ratio < 4.0: col4.success(f"🔥 Ratio: {ratio:.2f}")
            else: col4.info(f"⚖️ Ratio: {ratio:.2f}")
        else:
            col4.warning("Pas de cartes listées")

    if st.checkbox("Afficher Debug JSON"):
        st.json(st.session_state.get('last_debug', {}))
