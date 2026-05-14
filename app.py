import streamlit as st
import requests

# L'unique adresse pour parler à Sorare
API_URL = "https://api.sorare.com/graphql"

def sorare_sign_in(email, password, otp=None, otp_session_token=None):
    # La mutation officielle pour se connecter
    query = """
    mutation SignInMutation($input: SignInInput!) {
      signIn(input: $input) {
        token
        otpSessionToken
        errors { message }
      }
    }
    """
    input_data = {"email": email, "password": password}
    if otp:
        input_data["otp"] = otp
    if otp_session_token:
        input_data["otpSessionToken"] = otp_session_token

    response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}})
    return response.json()

# --- INTERFACE DE L'APPLICATION ---
st.title("🛡️ Test de Connexion Sorare")

# Gestion des états de la session (pour ne pas tout perdre à chaque clic)
if 'otp_token' not in st.session_state:
    st.session_state['otp_token'] = None
if 'final_token' not in st.session_state:
    st.session_state['final_token'] = None

# ÉTAPE 1 : Saisie Email + Mot de passe
if not st.session_state['otp_token'] and not st.session_state['final_token']:
    st.subheader("1. Identifiants")
    u_email = st.text_input("Ton Email Sorare")
    u_pass = st.text_input("Ton Mot de passe", type="password")
    
    if st.button("Lancer la connexion"):
        res = sorare_sign_in(u_email, u_pass)
        data = res.get('data', {}).get('signIn', {})
        
        if data.get('otpSessionToken'):
            # Sorare demande le code 2FA
            st.session_state['otp_token'] = data['otpSessionToken']
            st.session_state['temp_email'] = u_email
            st.session_state['temp_pass'] = u_pass
            st.rerun()
        elif data.get('token'):
            # Pas de 2FA (rare, mais possible)
            st.session_state['final_token'] = data['token']
            st.rerun()
        else:
            # Erreur (mauvais pass, etc.)
            st.error(f"Erreur : {data.get('errors')}")

# ÉTAPE 2 : Saisie du code OTP (2FA)
elif st.session_state['otp_token'] and not st.session_state['final_token']:
    st.subheader("2. Double Authentification")
    st.warning("Ouvre ton application d'authentification (Google Auth, etc.)")
    otp_code = st.text_input("Code à 6 chiffres", placeholder="123456")
    
    if st.button("Valider le code"):
        res = sorare_sign_in(
            st.session_state['temp_email'], 
            st.session_state['temp_pass'], 
            otp=otp_code, 
            otp_session_token=st.session_state['otp_token']
        )
        data = res.get('data', {}).get('signIn', {})
        
        if data.get('token'):
            st.session_state['final_token'] = data['token']
            st.success("✅ BRAVO ! Authentification réussie.")
            st.rerun()
        else:
            st.error("Code invalide. Réessaie.")
            if st.button("Recommencer au début"):
                st.session_state['otp_token'] = None
                st.rerun()

# ÉTAPE 3 : État Connecté
if st.session_state['final_token']:
    st.success("Tu es officiellement connecté à l'API.")
    st.write("C'est ce jeton (token) qui nous permettra de demander les prix en temps réel.")
    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_token'] = None
        st.rerun()
