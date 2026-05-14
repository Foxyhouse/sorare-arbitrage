import streamlit as st
import requests
import bcrypt

# Configuration Globale
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- FONCTIONS TECHNIQUES ---

def get_user_salt(email):
    """Récupère le sel (salt) unique de l'utilisateur."""
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
        if res.status_code == 200:
            return res.json().get("salt")
    except:
        return None
    return None

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    """Mutation de connexion conforme à la doc Sorare 2026."""
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "%s") {
          token
        }
        otpSessionChallenge
        errors { message }
      }
    }
    """ % AUDIENCE

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
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers)
        return response.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # On demande explicitement les cartes EN VENTE (onSale: true)
    # Et on utilise 'amount' qui est le champ standard pour le prix fixe
    query = """
    query GetFloorPrices($slugs: [String!]!) {
      players(slugs: $slugs) {
        ... on Player {
          displayName
          cards(rarities: [limited, rare], first: 50, onSale: true) {
            nodes {
              rarity
              price: amount { eur }
            }
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query, 'variables': {'slugs': [slug]}}, headers=headers)
        res_json = response.json()
        
        # Logique de récupération
        players_list = res_json.get('data', {}).get('players', [])
        if not players_list or players_list[0] is None:
            return None, None
            
        cards = players_list[0].get('cards', {}).get('nodes', [])
        
        lim_prices = []
        rare_prices = []
        
        for c in cards:
            if c.get('price') and c['price'].get('eur'):
                val = float(c['price']['eur'])
                if c['rarity'] == 'limited':
                    lim_prices.append(val)
                elif c['rarity'] == 'rare':
                    rare_prices.append(val)
        
        # On prend le prix le plus bas trouvé
        p_lim = min(lim_prices) if lim_prices else None
        p_rare = min(rare_prices) if rare_prices else None
        
        return p_lim, p_rare
    except Exception as e:
        # En cas d'erreur, on l'affiche discrètement dans la console Streamlit
        return None, None
            
        cards = players_list[0].get('cards', {}).get('nodes', [])
        lim_prices = []
        rare_prices = []
        
        for c in cards:
            if c.get('onSale') and c.get('priceData'):
                val = c['priceData'].get('eur')
                if val:
                    price = float(val)
                    if c['rarity'] == 'limited':
                        lim_prices.append(price)
                    elif c['rarity'] == 'rare':
                        rare_prices.append(price)
        
        p_lim = min(lim_prices) if lim_prices else None
        p_rare = min(rare_prices) if rare_prices else None
        
        return p_lim, p_rare
    except:
        return None, None

# --- INTERFACE STREAMLIT ---

st.set_page_config(page_title="Sorare Arbitrage Tool", page_icon="📈")
st.title("📈 Sorare Arbitrage Real-Time")

# Gestion de la session
if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# 1. PHASE D'AUTHENTIFICATION
if not st.session_state['final_token']:
    if not st.session_state['otp_challenge']:
        with st.form("login"):
            st.subheader("🔑 Connexion")
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter"):
                salt = get_user_salt(email)
                if salt:
                    # Hashage obligatoire selon la doc GitHub
                    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt.encode('utf-8')).decode('utf-8')
                    res = sorare_sign_in(email, hashed_password=hashed_pw)
                    data = res.get('data', {}).get('signIn', {})
                    
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'] = data['otpSessionChallenge']
                        st.session_state['temp_email'] = email
                        st.rerun()
                    elif data.get('jwtToken'):
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
                    else:
                        st.error(data.get('errors', [{}])[0].get('message', "Erreur de connexion."))
                else:
                    st.error("Impossible de récupérer le sel du compte.")
    else:
        with st.form("otp"):
            st.subheader("📱 Code 2FA")
            otp_code = st.text_input("Saisir le code à 6 chiffres")
            if st.form_submit_button("Valider"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
                data = res.get('data', {}).get('signIn', {})
                if data.get('jwtToken'):
                    st.session_state['final_token'] = data['jwtToken']['token']
                    st.rerun()
                else:
                    st.error("Code incorrect.")

# 2. DASHBOARD (CONNECTÉ)
else:
    st.success("✅ Connecté au marché Sorare")
    
    with st.sidebar:
        st.write(f"Session active : {st.session_state.get('temp_email', 'Jacques')}")
        if st.button("Se déconnecter"):
            st.session_state['final_token'] = None
            st.session_state['otp_challenge'] = None
            st.rerun()

    st.subheader("🔍 Monitoring des opportunités")
    
    # Ta liste de surveillance
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
            
            if ratio < 4.0:
                col4.success(f"🔥 Ratio: {ratio:.2f} (BUY !)")
            else:
                col4.info(f"⚖️ Ratio: {ratio:.2f}")
        else:
            col4.warning("Aucun prix trouvé sur le marché.")
        st.divider()

    st.caption("Données récupérées en direct via GraphQL API")
