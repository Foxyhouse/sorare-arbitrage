import streamlit as st
import requests

API_URL = "https://api.sorare.com/graphql"

def sorare_sign_in(email, password, otp=None, otp_session_token=None):
    # CHANGEMENT ICI : 'token' devient 'jwtToken'
    query = """
    mutation SignInMutation($input: SignInInput!) {
      signIn(input: $input) {
        jwtToken
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

    try:
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers)
        return response.json()
    except Exception as e:
        return {"error_exception": str(e)}

# --- INTERFACE ---
st.title("🛡️ Sorare Auth 2FA (Version Corrigée)")

if 'otp_token' not in st.session_state: st.session_state['otp_token'] = None
if 'final_token' not in st.session_state: st.session_state['final_token'] = None

# ÉTAPE 1 : Identifiants
if not st.session_state['otp_token'] and not st.session_state['final_token']:
    with st.form("login_form"):
        u_email = st.text_input("Email")
        u_pass = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Lancer la connexion")
        
        if submit:
            res = sorare_sign_in(u_email, u_pass)
            # Débogage visible si besoin
            if "errors" in res and not res.get("data"):
                st.error(f"Erreur schéma : {res['errors'][0]['message']}")
            else:
                data = res.get('data', {}).get('signIn', {})
                if data.get('otpSessionToken'):
                    st.session_state['otp_token'] = data['otpSessionToken']
                    st.session_state['temp_email'] = u_email
                    st.session_state['temp_pass'] = u_pass
                    st.rerun()
                elif data.get('jwtToken'): # CHANGEMENT ICI AUSSI
                    st.session_state['final_token'] = data['jwtToken']
                    st.rerun()
                else:
                    msg = data.get('errors', [{'message': 'Inconnu'}])[0]['message']
                    st.error(f"Erreur : {msg}")

# ÉTAPE 2 : OTP
elif st.session_state['otp_token'] and not st.session_state['final_token']:
    with st.form("otp_form"):
        st.info("Code 2FA requis")
        otp_code = st.text_input("Code (6 chiffres)")
        submit_otp = st.form_submit_button("Vérifier")
        
        if submit_otp:
            res = sorare_sign_in(
                st.session_state['temp_email'], 
                st.session_state['temp_pass'], 
                otp=otp_code, 
                otp_session_token=st.session_state['otp_token']
            )
            data = res.get('data', {}).get('signIn', {})
            if data.get('jwtToken'): # ET ICI
                st.session_state['final_token'] = data['jwtToken']
                st.success("✅ Connecté !")
                st.rerun()
            else:
                st.error("Code invalide.")

# ÉTAPE 3 : Dashboard
if st.session_state['final_token']:
    st.success("Authentification réussie !")
    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_token'] = None
        st.rerun()
