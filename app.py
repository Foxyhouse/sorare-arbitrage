import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION (Validée, on n'y touche plus) ---
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

# --- RÉCUPÉRATION DES PRIX (La nouvelle tentative) ---
def get_market_data(slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # STRATÉGIE : On ouvre le dossier 'all' à l'intérieur de 'tokens'
    # C'est la structure 'TokenRoot' la plus courante
    query = """
    query GetFloor($slug: String!) {
      tokens(playerSlugs: [$slug]) {
        all(rarities: [limited, rare]) {
          nodes {
            rarity
            price: amount { eur }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers).json()
        st.session_state['last_debug'] = res
        
        # On descend dans l'arborescence : tokens -> all -> nodes
        nodes = res.get('data', {}).get('tokens', {}).get('all', {}).get('nodes', [])
        
        lim_prices, rare_prices = [], []
        for n in nodes:
            p = n.get('price', {}).get('eur')
            if p:
                val = float(p)
                if n['rarity'] == 'limited': lim_prices.append(val)
                elif n['rarity'] == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, 
                min(rare_prices) if rare_prices else None)
    except:
        return None, None

# --- INTERFACE ---
st.set_page_config(page_title="Sorare Arbitrage V5", page_icon="📈")
st.title("📈 Sorare Arbitrage (Version Stable)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    # Bloc de connexion
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

    st.subheader("📊 Suivi Koffi & Lefort")
    watchlist = {"Hervé Koffi": "kouakou-herve-koffi", "Jordan Lefort": "jordan-lefort"}
    
    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        
        if p_lim: col2.metric("Limited", f"{p_lim}€")
        if p_rare: col3.metric("Rare", f"{p_rare}€")
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            if ratio < 4: col4.success(f"🔥 Ratio: {ratio:.2f}")
            else: col4.info(f"⚖️ Ratio: {ratio:.2f}")
        else:
            col4.warning("Données en attente...")

    if st.checkbox("Afficher Debug JSON"):
        st.json(st.session_state.get('last_debug', {}))
