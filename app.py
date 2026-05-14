import streamlit as st
import requests

API_URL = "https://api.sorare.com/graphql"

def sorare_sign_in(email, password, otp=None, otp_session_challenge=None):
    # MISE À JOUR : On utilise désormais 'otpSessionChallenge'
    query = """
    mutation SignInMutation($input: SignInInput!) {
      signIn(input: $input) {
        jwtToken
        otpSessionChallenge
        errors { message }
      }
    }
    """
    input_data = {"email": email, "password": password}
    if otp:
        input_data["otp"] = otp
    if otp_session_challenge:
        input_data["otpSessionChallenge"] = otp_session_challenge

    try:
        headers = {"User-Agent": "SorareArbitrageBot/1.0"}
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers)
        return response.json()
    except Exception as e:
        return {"error_exception": str(e)}

# --- INTERFACE ---
st.title("🛡️ Sorare Auth 2FA (Version Challenge)")

# On adapte aussi les noms dans la mémoire de l'appli (session_state)
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None
if 'final_token' not in st.session_state: st.session_state['final_token'] = None

# ÉTAPE 1 : Email + Pass
if not st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("login_form"):
        u_email = st.text_input("Email", value="jacques.troispoils@gmail.com") # J'ai pré-rempli selon ton screen
        u_pass = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Lancer la connexion")
        
        if submit:
            res = sorare_sign_in(u_email, u_pass)
            
            if "errors" in res and not res.get("data"):
                st.error(f"Erreur schéma : {res['errors'][0]['message']}")
            else:
                data = res.get('data', {}).get('signIn', {})
                if data.get('otpSessionChallenge'):
                    # Succès étape 1 !
                    st.session_state['otp_challenge'] = data['otpSessionChallenge']
                    st.session_state['temp_email'] = u_email
                    st.session_state['temp_pass'] = u_pass
                    st.rerun()
                elif data.get('jwtToken'):
                    st.session_state['final_token'] = data['jwtToken']
                    st.rerun()
                else:
                    msg = data.get('errors', [{'message': 'Identifiants invalides'}])[0]['message']
                    st.error(f"Erreur : {msg}")

# ÉTAPE 2 : Code OTP
elif st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("otp_form"):
        st.warning("📱 Code 2FA requis (Google Authenticator)")
        otp_code = st.text_input("Saisir les 6 chiffres")
        submit_otp = st.form_submit_button("Valider")
        
        if submit_otp:
            res = sorare_sign_in(
                st.session_state['temp_email'], 
                st.session_state['temp_pass'], 
                otp=otp_code, 
                otp_session_challenge=st.session_state['otp_challenge']
            )
            data = res.get('data', {}).get('signIn', {})
            if data.get('jwtToken'):
                st.session_state['final_token'] = data['jwtToken']
                st.success("✅ Enfin connecté !")
                st.rerun()
            else:
                st.error("Code OTP incorrect ou expiré.")
                if st.button("Retour"):
                    st.session_state['otp_challenge'] = None
                    st.rerun()

# ÉTAPE 3 : État Connecté
if st.session_state['final_token']:
    st.balloons()
    st.success("Authentification réussie ! Le 'jwtToken' est prêt.")
    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()
