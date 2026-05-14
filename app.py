import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"

# 1. Fonction pour récupérer le sel (Salt)
def get_user_salt(email):
    res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
    if res.status_code == 200:
        return res.json().get("salt")
    return None

# 2. Fonction de connexion (Mutation officielle)
def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") {
          token
        }
        otpSessionChallenge
        errors { message }
      }
    }
    """
    # Construction de l'input selon la doc
    if otp_session_challenge:
        input_data = {
            "otpSessionChallenge": otp_session_challenge,
            "otpAttempt": otp_attempt # La doc dit 'otpAttempt'
        }
    else:
        input_data = {
            "email": email,
            "password": hashed_password
        }

    response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}})
    return response.json()

# --- INTERFACE ---
st.title("⚽ Sorare Auth (Conforme GitHub Doc)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# ÉTAPE 1 : Email + Password (Hashé)
if not st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("login"):
        u_email = st.text_input("Email")
        u_pass = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            # A. Récupérer le sel
            salt = get_user_salt(u_email)
            if salt:
                # B. Hasher le mot de passe (Important !)
                hashed_pw = bcrypt.hashpw(u_pass.encode('utf-8'), salt.encode('utf-8')).decode('utf-8')
                
                # C. Envoyer la mutation
                res = sorare_sign_in(u_email, hashed_password=hashed_pw)
                data = res.get('data', {}).get('signIn', {})
                
                if data.get('otpSessionChallenge'):
                    st.session_state['otp_challenge'] = data['otpSessionChallenge']
                    st.session_state['temp_email'] = u_email
                    st.rerun()
                elif data.get('jwtToken'):
                    st.session_state['final_token'] = data['jwtToken']['token']
                    st.rerun()
                else:
                    st.error(data.get('errors', [{}])[0].get('message', "Erreur inconnue"))
            else:
                st.error("Utilisateur introuvable.")

# ÉTAPE 2 : OTP (2FA)
elif st.session_state['otp_challenge'] and not st.session_state['final_token']:
    otp_code = st.text_input("Code 2FA (6 chiffres)")
    if st.button("Valider"):
        res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
        data = res.get('data', {}).get('signIn', {})
        if data.get('jwtToken'):
            st.session_state['final_token'] = data['jwtToken']['token']
            st.rerun()
        else:
            st.error("Code invalide.")

# ÉTAPE 3 : Dashboard (Une fois connecté)
if st.session_state['final_token']:
    st.success("✅ Connecté avec succès !")
    
    # Configuration des headers selon la doc GitHub
    # Note : la doc exige le header JWT-AUD identique à celui utilisé lors du login
    headers = {
        "Authorization": f"Bearer {st.session_state['final_token']}",
        "JWT-AUD": "sorare-app",
        "Content-Type": "application/json"
    }

    def get_market_data(slug):
        query = """
        query GetFloorPrices($slug: String!) {
          player(slug: $slug) {
            displayName
            limited: cards(rarities: [limited], first: 1, publicSearch: true) {
              nodes { amounts { eur } }
            }
            rare: cards(rarities: [rare], first: 1, publicSearch: true) {
              nodes { amounts { eur } }
            }
          }
        }
        """
        try:
            response = requests.post(API_URL, json={'query': query, 'variables': {'slug': slug}}, headers=headers)
            data = response.json().get('data', {}).get('player', {})
            
            p_lim = data['limited']['nodes'][0]['amounts']['eur']
            p_rare = data['rare']['nodes'][0]['amounts']['eur']
            return p_lim, p_rare
        except:
            return None, None

    # --- TON MONITORING ---
    st.divider()
    st.subheader("🕵️‍♂️ Opportunités d'Arbitrage en Direct")
    
    # On définit tes cibles
    targets = {
        "Hervé Koffi": "herve-koffi",
        "Jordan Lefort": "jordan-lefort"
    }

    # Création d'un tableau propre
    for name, slug in targets.items():
        p_lim, p_rare = get_market_data(slug)
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            with col1:
                st.markdown(f"**{name}**")
            with col2:
                st.write(f"L: {p_lim}€")
            with col3:
                st.write(f"R: {p_rare}€")
            with col4:
                # La règle d'or : Gain x4 / Prix < x4
                if ratio < 4.0:
                    st.success(f"🔥 Ratio: {ratio:.2f} | ACHÈTE RARE")
                else:
                    st.info(f"⚖️ Ratio: {ratio:.2f} | Reste en Limited")
        else:
            st.error(f"Données indisponibles pour {name}")

    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()
