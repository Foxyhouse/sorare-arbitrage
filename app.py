import streamlit as st
import requests

API_URL = "https://api.sorare.com/graphql"

def sorare_sign_in(email, password, otp=None, otp_session_challenge=None):
    # MISE À JOUR : On ajoute l'argument (aud: "sorare") requis par le schéma 2026
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare") {
          token
        }
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
st.title("🛡️ Sorare Auth 2FA (Fix Argument 'aud')")

if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None
if 'final_token' not in st.session_state: st.session_state['final_token'] = None

# ÉTAPE 1 : Connexion initiale
if not st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("login_form"):
        u_email = st.text_input("Email", value="jacques.troispoils@gmail.com")
        u_pass = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Lancer la connexion")
        
        if submit:
            res = sorare_sign_in(u_email, u_pass)
            
            if "errors" in res and not res.get("data"):
                st.error(f"Erreur API : {res['errors'][0]['message']}")
            else:
                data = res.get('data', {}).get('signIn', {})
                if data:
                    if data.get('otpSessionChallenge'):
                        st.session_state['otp_challenge'] = data['otpSessionChallenge']
                        st.session_state['temp_email'] = u_email
                        st.session_state['temp_pass'] = u_pass
                        st.rerun()
                    elif data.get('jwtToken'): 
                        st.session_state['final_token'] = data['jwtToken']['token']
                        st.rerun()
                    elif data.get('errors'):
                        st.error(f"Erreur : {data['errors'][0]['message']}")
                else:
                    st.error("Réponse vide.")

# ÉTAPE 2 : Saisie du code OTP
elif st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("otp_form"):
        st.warning("📱 Code 2FA requis")
        otp_code = st.text_input("Saisir les 6 chiffres")
        submit_otp = st.form_submit_button("Valider")
        
        if submit_otp:
            # Note : on réutilise la même fonction qui contient maintenant (aud: "sorare")
            res = sorare_sign_in(
                st.session_state['temp_email'], 
                st.session_state['temp_pass'], 
                otp=otp_code, 
                otp_session_challenge=st.session_state['otp_challenge']
            )
            data = res.get('data', {}).get('signIn', {})
            if data and data.get('jwtToken'):
                st.session_state['final_token'] = data['jwtToken']['token']
                st.rerun()
            else:
                st.error("Code incorrect ou expiré.")

# ÉTAPE 3 : Succès
if st.session_state['final_token']:
    st.balloons()
    st.success("✅ Enfin ! Authentification réussie avec Audience validée.")
    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()
