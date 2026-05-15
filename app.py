import streamlit as st
import requests
import bcrypt

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- AUTHENTIFICATION ---
def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        if res.status_code == 200:
            return res.json().get("salt")
    except:
        return None
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
    if otp_session_challenge:
        input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt}
    else:
        input_data = {"email": email, "password": hashed_password}
        
    try:
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        res = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers, timeout=10)
        return res.json()
    except Exception as e:
        return {"errors": [{"message": str(e)}]}

# --- LOGIQUE DE MARCHÉ (CORRECTION SENDER_SIDE) ---
def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # Chemin définitif selon le schéma : 
    # TokenOffer -> senderSide (ce que le vendeur donne) -> anyCards -> rarityTyped
    query = """
    query GetFloor($slug: String!) {
      tokens {
        liveSingleSaleOffers(playerSlug: $slug) {
          nodes {
            senderSide {
              anyCards {
                rarityTyped
              }
            }
            receiverSide {
              amounts {
                wei
              }
            }
          }
        }
      }
    }
    """
    
    try:
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers, timeout=10).json()
        st.session_state['last_debug'] = res 
        
        if "errors" in res:
            return None, None

        offers = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        lim_prices, rare_prices = [], []
        
        for offer in offers:
            # Récupération de la rareté via senderSide -> anyCards
            sender_side = offer.get('senderSide', {})
            cards = sender_side.get('anyCards', [])
            if not cards:
                continue
            
            rarity = str(cards[0].get('rarityTyped', '')).lower()
            
            # Récupération du prix via receiverSide -> amounts -> wei
            wei_val = offer.get('receiverSide', {}).get('amounts', {}).get('wei')
            
            if wei_val:
                price_eth = float(wei_val) / 1e18
                if rarity == 'limited':
                    lim_prices.append(price_eth)
                elif rarity == 'rare':
                    rare_prices.append(price_eth)
        
        p_lim = min(lim_prices) if lim_prices else None
        p_rare = min(rare_prices) if rare_prices else None
        return p_lim, p_rare
    except Exception as e:
        return None, None

# --- INTERFACE ---
st.set_page_config(page_title="Arbitrage Sorare 2026", page_icon="🎯", layout="wide")
st.title("🎯 Sorare Arbitrage Real-Time")

if 'token' not in st.session_state: st.session_state['token'] = None
if 'otp' not in st.session_state: st.session_state['otp'] = None

if not st.session_state['token']:
    col_log, _ = st.columns([1, 2])
    with col_log:
        if not st.session_state['otp']:
            with st.form("login"):
                st.subheader("🔑 Connexion")
                email = st.text_input("Email", value="jacques.troispoils@gmail.com")
                pwd = st.text_input("Mot de passe", type="password")
                if st.form_submit_button("Se connecter"):
                    salt = get_user_salt(email)
                    if salt:
                        hpwd = bcrypt.hashpw(pwd.encode(), salt.encode()).decode()
                        res = sorare_sign_in(email, hpwd)
                        data = res.get('data', {}).get('signIn', {})
                        if data.get('otpSessionChallenge'):
                            st.session_state['otp'] = data['otpSessionChallenge']
                            st.session_state['mail'] = email
                            st.rerun()
                        elif data.get('jwtToken'):
                            st.session_state['token'] = data['jwtToken']['token']
                            st.rerun()
                        else:
                            st.error("Erreur d'identifiants.")
                    else:
                        st.error("Compte introuvable.")
        else:
            with st.form("otp_form"):
                st.subheader("📱 Code 2FA")
                code = st.text_input("Saisir le code")
                if st.form_submit_button("Valider"):
                    res = sorare_sign_in(st.session_state['mail'], otp_attempt=code, otp_session_challenge=st.session_state['otp'])
                    if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                        st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                        st.rerun()
                    else:
                        st.error("Code erroné.")
else:
    st.sidebar.success("✅ Connecté")
    if st.sidebar.button("Déconnecter"):
        st.session_state['token'] = None
        st.session_state['otp'] = None
        st.rerun()

    watchlist = {
        "Hervé Koffi": "kouakou-herve-koffi",
        "Jordan Lefort": "jordan-lefort",
        "Lucas Chevalier": "lucas-chevalier"
    }

    st.subheader("🚀 Opportunités de marché")
    
    for name, slug in watchlist.items():
        with st.container():
            p_lim, p_rare = get_market_data(slug, st.session_state['token'])
            c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
            c1.markdown(f"### {name}")
            
            if p_lim: c2.metric("Floor Limited", f"{p_lim:.4f} Ξ")
            else: c2.caption("Aucune Limited")
            
            if p_rare: c3.metric("Floor Rare", f"{p_rare:.4f} Ξ")
            else: c3.caption("Aucune Rare")

            if p_lim and p_rare:
                ratio = p_rare / p_lim
                if ratio < 4.0:
                    c4.success(f"🔥 Ratio : {ratio:.2f}")
                else:
                    c4.info(f"Ratio : {ratio:.2f}")
            st.divider()

    if st.checkbox("🔍 Debug JSON"):
        st.json(st.session_state.get('last_debug', {}))
