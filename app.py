import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- LOGIQUE TECHNIQUE ---

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
    try:
        return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()
    except Exception as e: return {"errors": [{"message": str(e)}]}

def get_market_data(slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # REQUÊTE MISE À JOUR : On sépare Limited et Rare pour plus de clarté
    query = """
    query GetFloor($slugs: [String!]!) {
      players(slugs: $slugs) {
        ... on Player {
          displayName
          limitedFloor: cards(rarities: [limited], first: 1, onSale: true, publicSearch: true) {
            nodes { amount { eur } }
          }
          rareFloor: cards(rarities: [rare], first: 1, onSale: true, publicSearch: true) {
            nodes { amount { eur } }
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query, 'variables': {'slugs': [slug]}}, headers=headers)
        res_json = response.json()
        
        # On stocke la réponse brute pour le débug
        st.session_state['last_debug'] = res_json 
        
        player = res_json.get('data', {}).get('players', [None])[0]
        if not player: return None, None
        
        # Extraction sécurisée
        try:
            p_lim = player['limitedFloor']['nodes'][0]['amount']['eur']
        except: p_lim = None
            
        try:
            p_rare = player['rareFloor']['nodes'][0]['amount']['eur']
        except: p_rare = None
            
        return p_lim, p_rare
    except:
        return None, None

# --- INTERFACE ---

st.set_page_config(page_title="Sorare Bot V3", page_icon="🕵️‍♂️")
st.title("🕵️‍♂️ Sorare Arbitrage (Deep Scan)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    # --- BLOC CONNEXION (Identique au précédent) ---
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            e = st.text_input("Email", value="jacques.troispoils@gmail.com")
            p = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Connexion"):
                salt = get_user_salt(e)
                if salt:
                    hpw = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                    res = sorare_sign_in(e, hashed_password=hpw)
                    data = res.get('data', {}).get('signIn', {})
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'], st.session_state['temp_email'] = data['otpSessionChallenge'], e
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
    else:
        otp = st.text_input("Code 2FA")
        if st.button("Valider"):
            res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp, otp_session_challenge=st.session_state['otp_challenge'])
            if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                st.session_state['final_token'] = res['data']['signIn']['jwtToken']['token']
                st.rerun()

else:
    st.success("✅ Tuyaux connectés !")
    
    # Sidebar de contrôle
    with st.sidebar:
        if st.button("Déconnexion"):
            st.session_state['final_token'] = None
            st.rerun()
        st.divider()
        show_debug = st.checkbox("Afficher la réponse brute (Debug)")

    # Dashboard
    watchlist = {
        "Hervé Koffi": "kouakou-herve-koffi",
        "Jordan Lefort": "jordan-lefort"
    }

    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        
        if p_lim and p_rare:
            ratio = float(p_rare) / float(p_lim)
            col2.metric("Limited", f"{p_lim}€")
            col3.metric("Rare", f"{p_rare}€")
            if ratio < 4: col4.success(f"Ratio: {ratio:.2f} 🔥")
            else: col4.info(f"Ratio: {ratio:.2f}")
        else:
            col4.warning("Données introuvables")

    # Affichage du debug si coché
    if show_debug and 'last_debug' in st.session_state:
        st.divider()
        st.subheader("🛠️ Zone de Debug (JSON)")
        st.json(st.session_state['last_debug'])
