import streamlit as st
import requests
import bcrypt

# Configuration
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- FONCTIONS TECHNIQUES ---

def get_user_salt(email):
    """Récupère le sel unique de l'utilisateur pour le hashage."""
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
        if res.status_code == 200:
            return res.json().get("salt")
    except:
        return None
    return None

def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    """Effectue la mutation de connexion (Etape 1 ou Etape 2 avec OTP)."""
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
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}})
        return response.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

def get_market_data(slug, jwt_token):
    """Récupère les prix planchers (Floor) via l'interface Player."""
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE
    }
    query = """
    query GetFloorPrices($slugs: [String!]!) {
      players(slugs: $slugs) {
        ... on Player {
          displayName
          cards(rarities: [limited, rare], first: 50) {
            nodes {
              rarity
              onSale
              priceEur: amountNextStep { eur }
            }
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query, 'variables': {'slugs': [slug]}}, headers=headers)
        data = response.json().get('data', {}).get('players', [])
        
        if not data or data[0] is None:
            return None, None
            
        cards = data[0].get('cards', {}).get('nodes', [])
        lim_prices = [c['priceEur']['eur'] for c in cards if c['rarity'] == 'limited' and c.get('onSale') and c.get('priceEur')]
        rare_prices = [c['priceEur']['eur'] for c in cards if c['rarity'] == 'rare' and c.get('onSale') and c.get('priceEur')]
        
        p_lim = min(lim_prices) if lim_prices else None
        p_rare = min(rare_prices) if rare_prices else None
        
        return p_lim, p_rare
    except:
        return None, None

# --- INTERFACE UTILISATEUR (STREAMLIT) ---

st.set_page_config(page_title="Sorare Arbitrage Bot", page_icon="🚀")
st.title("🚀 Sorare Arbitrage Real-Time")

# Initialisation de la session
if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# --- ETAPE 1 & 2 : AUTHENTIFICATION ---
if not st.session_state['final_token']:
    # Formulaire de login classique
    if not st.session_state['otp_challenge']:
        with st.form("login_form"):
            st.subheader("🔑 Connexion Sorare")
            email = st.text_input("Email", value="jacques.troispoils@gmail.com")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Lancer la connexion"):
                salt = get_user_salt(email)
                if salt:
                    # Hashage Bcrypt obligatoire
                    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt.encode('utf-8')).decode('utf-8')
                    res = sorare_sign_in(email, hashed_password=hashed_pw)
                    
                    data = res.get('data', {}).get('signIn', {})
                    if data:
                        if data.get('otpSessionChallenge'):
                            st.session_state['otp_challenge'] = data['otpSessionChallenge']
                            st.session_state['temp_email'] = email
                            st.rerun()
                        elif data.get('jwtToken'):
                            st.session_state['final_token'] = data['jwtToken']['token']
                            st.rerun()
                    else:
                        st.error(res.get('errors', [{}])[0].get('message', "Erreur inconnue"))
                else:
                    st.error("Impossible de récupérer le sel du compte.")
    
    # Formulaire OTP (si challenge activé)
    else:
        with st.form("otp_form"):
            st.subheader("📱 Double Authentification")
            otp_code = st.text_input("Code de ton appli 2FA")
            if st.form_submit_button("Valider le code"):
                res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
                data = res.get('data', {}).get('signIn', {})
                if data and data.get('jwtToken'):
                    st.session_state['final_token'] = data['jwtToken']['token']
                    st.rerun()
                else:
                    st.error("Code invalide. Réessaie.")

# --- ETAPE 3 : DASHBOARD D'ARBITRAGE ---
else:
    st.success("✅ Connecté à l'API Sorare")
    
    with st.sidebar:
        st.write(f"Connecté en tant que : {st.session_state.get('temp_email', 'Utilisateur')}")
        if st.button("Se déconnecter"):
            st.session_state['final_token'] = None
            st.session_state['otp_challenge'] = None
            st.rerun()

    st.subheader("🕵️‍♂️ Monitoring des Ratios Rare/Limited")
    
    # Liste de tes joueurs cibles
    watchlist = {
        "Hervé Koffi": "kouakou-herve-koffi",
        "Jordan Lefort": "jordan-lefort"
    }

    for name, slug in watchlist.items():
        p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
        
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            
            if p_lim and p_rare:
                ratio = p_rare / p_lim
                col1.markdown(f"**{name}**")
                col2.metric("Limited", f"{p_lim}€")
                col3.metric("Rare", f"{p_rare}€")
                
                # Logique métier : Ratio < 4 = Opportunité
                if ratio < 4.0:
                    col4.success(f"🎯 Ratio: {ratio:.2f} (BUY !)")
                else:
                    col4.info(f"⚖️ Ratio: {ratio:.2f}")
            else:
                col1.markdown(f"**{name}**")
                col4.warning("Aucune carte en vente directe.")
        st.divider()

    st.caption("Données actualisées en temps réel via Sorare API v2026")
