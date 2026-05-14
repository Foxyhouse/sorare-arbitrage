import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTH (Fonctionne déjà) ---
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

# --- SCANNER AMÉLIORÉ (Affiche les erreurs !) ---
def deep_scan(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    # On demande les champs de base ET leur type pour comprendre la structure
    query = """
    query {
      __schema {
        queryType {
          fields {
            name
            type { name kind }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        if "errors" in res:
            return f"Erreur API : {res['errors'][0]['message']}"
        fields = res['data']['__schema']['queryType']['fields']
        return [f"{f['name']} ({f['type']['name'] or f['type']['kind']})" for f in fields]
    except Exception as e:
        return f"Erreur technique : {str(e)}"

# --- FETCH MULTI-TENTATIVES ---
def get_market_data(slug, jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE}
    
    # On va essayer la structure "TokenRoot" simplifiée sans edges/nodes
    query = """
    query GetFloor($slug: String!) {
      tokens(playerSlugs: [$slug], rarities: [limited, rare]) {
        rarity
        priceEur: amount { eur }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers).json()
        st.session_state['last_debug'] = res
        
        # Si 'tokens' est une liste directe (sans nodes/edges)
        token_list = res.get('data', {}).get('tokens', [])
        if not isinstance(token_list, list): return None, None
        
        lim_prices, rare_prices = [], []
        for t in token_list:
            p = t.get('priceEur', {}).get('eur')
            if p:
                val = float(p)
                if t['rarity'] == 'limited': lim_prices.append(val)
                elif t['rarity'] == 'rare': rare_prices.append(val)
        
        return (min(lim_prices) if lim_prices else None, min(rare_prices) if rare_prices else None)
    except: return None, None

# --- INTERFACE ---
st.title("🚀 Sorare Diagnostic V4")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

if not st.session_state['final_token']:
    # Bloc Connexion (Reste tel quel)
    with st.form("login"):
        u_email = st.text_input("Email", value="jacques.troispoils@gmail.com")
        u_pass = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Connexion"):
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
    
    # --- ZONE DE SCAN ---
    with st.expander("🔍 SCANNER DE STRUCTURE (À lancer en premier)"):
        if st.button("Lancer le Diagnostic Profond"):
            results = deep_scan(st.session_state['final_token'])
            if isinstance(results, list):
                st.write("### Champs trouvés à la racine :")
                st.info(", ".join(results))
            else:
                st.error(results)

    # --- DASHBOARD ---
    watchlist = {"Hervé Koffi": "kouakou-herve-koffi", "Jordan Lefort": "jordan-lefort"}
    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
        col1.markdown(f"**{name}**")
        if p_lim: col2.metric("Limited", f"{p_lim}€")
        if p_rare: col3.metric("Rare", f"{p_rare}€")
        if not p_lim and not p_rare: col4.warning("Données absentes")

    if st.checkbox("Afficher le JSON de Debug"):
        st.json(st.session_state.get('last_debug', {}))
