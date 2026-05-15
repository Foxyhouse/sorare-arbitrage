import streamlit as st
import requests
import bcrypt
import time

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

# --- FONCTIONS AUTHENTIFICATION ---
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

# --- FONCTION DE RÉCUPÉRATION DES PRIX (STRATÉGIE 2026) ---
def get_market_data(slug, jwt_token):
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "JWT-AUD": AUDIENCE,
        "Content-Type": "application/json"
    }
    
    # Stratégie robuste : on utilise cardSet avec l'objet de base CardSetRoot
    query = """
    query GetFloor($slug: String!) {
      cardSet(playerSlugs: [$slug]) {
        ... on CardSetRoot {
          cards(rarities: [limited, rare]) {
            nodes {
              rarity
              liveSingleSaleOffer {
                receiverSide {
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
        res = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers, timeout=10).json()
        st.session_state['last_debug'] = res 
        
        if "errors" in res:
            return None, None

        card_set = res.get('data', {}).get('cardSet', {})
        if not card_set:
            return None, None
            
        cards_data = card_set.get('cards', {})
        nodes = cards_data.get('nodes', [])
        
        lim_prices, rare_prices = [], []
        for n in nodes:
            offer = n.get('liveSingleSaleOffer')
            if offer and offer.get('receiverSide', {}).get('wei'):
                price_wei = offer['receiverSide']['wei']
                price_eth = float(price_wei) / 1e18
                rarity = str(n.get('rarity')).lower()
                if rarity == 'limited':
                    lim_prices.append(price_eth)
                elif rarity == 'rare':
                    rare_prices.append(price_eth)
        
        p_lim = min(lim_prices) if lim_prices else None
        p_rare = min(rare_prices) if rare_prices else None
        return p_lim, p_rare
    except:
        return None, None

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Sorare Arbitrage 2026", page_icon="🎯", layout="wide")

# Outil de secours pour Chromebook bridé
with st.expander("🛠️ Outils de Diagnostic (Chromebook)"):
    st.write("Si l'application affiche des erreurs de schéma, télécharge le fichier ci-dessous et envoie-le moi.")
    if st.button("Récupérer le Schéma API"):
        try:
            r = requests.get("https://api.sorare.com/graphql/schema")
            st.download_button("Enregistrer schema.graphql", r.text, "schema.graphql")
            st.success("Schéma récupéré avec succès !")
        except:
            st.error("Impossible de joindre Sorare pour le schéma.")

st.title("🎯 Sorare Arbitrage Real-Time")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# --- SYSTÈME DE CONNEXION ---
if not st.session_state['final_token']:
    col_login, _ = st.columns([1, 2])
    with col_login:
        if not st.session_state['otp_challenge']:
            with st.form("login_form"):
                st.subheader("🔑 Connexion Sorare")
                email = st.text_input("Email", value="jacques.troispoils@gmail.com")
                password = st.text_input("Mot de passe", type="password")
                submit = st.form_submit_button("Se connecter")
                
                if submit:
                    salt = get_user_salt(email)
                    if salt:
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
                            st.error(f"Erreur : {res.get('errors', [{}])[0].get('message', 'Vérifiez vos identifiants')}")
                    else:
                        st.error("Impossible de récupérer les informations de sécurité du compte.")
        else:
            with st.form("otp_form"):
                st.subheader("📱 Double Authentification")
                st.info("Saisissez le code de votre application 2FA.")
                otp_code = st.text_input("Code 6 chiffres")
                if st.form_submit_button("Valider"):
                    res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
                    token_data = res.get('data', {}).get('signIn', {}).get('jwtToken')
                    if token_data:
                        st.session_state['final_token'] = token_data['token']
                        st.rerun()
                    else:
                        st.error("Code incorrect ou expiré.")

# --- DASHBOARD PRINCIPAL ---
else:
    st.sidebar.success("✅ Connecté au marché")
    if st.sidebar.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()

    st.subheader("🚀 Monitoring des Arbitrages Limited / Rare")
    
    # Watchlist personnalisable
    watchlist = {
        "Hervé Koffi": "kouakou-herve-koffi",
        "Jordan Lefort": "jordan-lefort",
        "Lucas Chevalier": "lucas-chevalier"
    }

    # Affichage en colonnes
    cols = st.columns(len(watchlist))
    
    for idx, (name, slug) in enumerate(watchlist.items()):
        with cols[idx]:
            st.markdown(f"#### {name}")
            p_lim, p_rare = get_market_data(slug, st.session_state['final_token'])
            
            if p_lim:
                st.metric("Limited (Floor)", f"{p_lim:.4f} Ξ")
            else:
                st.caption("Aucune Limited en vente")
            
            if p_rare:
                st.metric("Rare (Floor)", f"{p_rare:.4f} Ξ")
            else:
                st.caption("Aucune Rare en vente")

            if p_lim and p_rare:
                ratio = p_rare / p_lim
                if ratio < 4.0:
                    st.success(f"🔥 Ratio: {ratio:.2f}")
                else:
                    st.info(f"Ratio: {ratio:.2f}")
            
            st.divider()

    if st.checkbox("⚙️ Mode Debug (Afficher JSON API)"):
        st.json(st.session_state.get('last_debug', {}))
