import streamlit as st
import requests
import bcrypt

# Configuration
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- FONCTIONS DE SÉCURITÉ ---

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

# --- OUTILS D'EXPLORATION (POUR NE PLUS TÂTONNER) ---

def scan_api_fields(jwt_token):
    """Scanne tous les champs disponibles à la racine de l'API."""
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    query = """
    query {
      __type(name: "Query") {
        fields { name }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        return [f['name'] for f in res['data']['__type']['fields']]
    except: return []

# --- RÉCUPÉRATION DES PRIX (STRATÉGIE "BEST GUESS") ---

def get_market_data(slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # On tente la structure la plus probable selon tes dernières erreurs
    query = """
    query GetFloor($slug: String!) {
      tokens(playerSlugs: [$slug], rarities: [limited, rare]) {
        edges {
          node {
            rarity
            activeListing { price { eur } }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers).json()
        st.session_state['last_debug'] = res
        
        edges = res.get('data', {}).get('tokens', {}).get('edges', [])
        lim_prices = []
        rare_prices = []
        
        for edge in edges:
            node = edge.get('node', {})
            price = node.get('activeListing', {}).get('price', {}).get('eur')
            if price:
                val = float(price)
                if node['rarity'] == 'limited': lim_prices.append(val)
                elif node['rarity'] == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, 
                min(rare_prices) if rare_prices else None)
    except: return None, None

# --- INTERFACE UTILISATEUR ---

st.set_page_config(page_title="Sorare Arbitrage Bot", page_icon="⚽")
st.title("⚽ Sorare Arbitrage (Scanner Edition)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# SECTION 1 : CONNEXION
if not st.session_state['final_token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.subheader("🔑 Étape 1 : Connexion sécurisée")
            u_email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            u_pass = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Lancer l'authentification"):
                salt = get_user_salt(u_email)
                if salt:
                    hpw = bcrypt.hashpw(u_pass.encode(), salt.encode()).decode()
                    res = sorare_sign_in(u_email, hashed_password=hpw)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'] = data['otpSessionChallenge']
                        st.session_state['temp_email'] = u_email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
                    else: st.error("Erreur d'identifiants.")
                else: st.error("Utilisateur introuvable.")
    else:
        with st.form("otp"):
            st.subheader("📱 Étape 2 : Code 2FA")
            code = st.text_input("Saisir les 6 chiffres")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=code, otp_session_challenge=st.session_state['otp_challenge'])
                token = res.get('data', {}).get('signIn', {}).get('jwtToken', {}).get('token')
                if token:
                    st.session_state['final_token'] = token
                    st.rerun()
                else: st.error("Code incorrect.")

# SECTION 2 : DASHBOARD & SCANNER
else:
    st.sidebar.success("✅ Session Active")
    if st.sidebar.button("Déconnexion"):
        st.session_state['final_token'] = None
        st.rerun()

    # --- LE SCANNER (TA MEILLEURE ARME) ---
    with st.expander("🔍 Explorateur de Schéma (Si rien ne s'affiche)"):
        if st.button("Scanner les champs de l'API"):
            fields = scan_api_fields(st.session_state['final_token'])
            st.write("Voici les mots-clés que l'API accepte en ce moment :")
            st.code(", ".join(fields))
            st.info("Cherche des mots comme 'market', 'allCards', ou 'floorPrices'.")

    # --- MONITORING ---
    st.subheader("📊 Ratios Koffi & Lefort")
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
            col2.write(f"L: {p_lim}€")
            col3.write(f"R: {p_rare}€")
            if ratio < 4: col4.success(f"🔥 Ratio: {ratio:.2f}")
            else: col4.info(f"⚖️ Ratio: {ratio:.2f}")
        else:
            col4.warning("En attente de données...")

    if st.checkbox("Afficher le JSON de Debug"):
        st.json(st.session_state.get('last_debug', {}))
