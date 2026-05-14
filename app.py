import streamlit as st
import requests

API_URL = "https://api.sorare.com/graphql"

def sorare_sign_in(email, password, otp=None, otp_session_token=None):
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

    try:
        # Ajout d'un User-Agent pour éviter d'être bloqué comme un robot
        headers = {"User-Agent": "Mozilla/5.0 (SorareArbitrageBot/1.0)"}
        response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}, headers=headers)
        return response.json()
    except Exception as e:
        return {"error_exception": str(e)}

st.title("🛡️ Débug Connexion Sorare")

if 'otp_token' not in st.session_state: st.session_state['otp_token'] = None
if 'final_token' not in st.session_state: st.session_state['final_token'] = None

# ÉTAPE 1
if not st.session_state['otp_token'] and not st.session_state['final_token']:
    u_email = st.text_input("Email")
    u_pass = st.text_input("Mot de passe", type="password")
    
    if st.button("Lancer la connexion"):
        res = sorare_sign_in(u_email, u_pass)
        
        # --- ZONE DE DÉBUG ---
        st.write("🔍 Réponse brute de Sorare :", res)
        # ---------------------

        if 'errors' in res and not res.get('data'):
             st.error(f"Erreur API (Root) : {res['errors'][0]['message']}")
        else:
            data = res.get('data', {}).get('signIn', {})
            if data:
                if data.get('otpSessionToken'):
                    st.session_state['otp_token'] = data['otpSessionToken']
                    st.session_state['temp_email'] = u_email
                    st.session_state['temp_pass'] = u_pass
                    st.success("Étape 1 réussie, en attente de l'OTP...")
                    st.rerun()
                elif data.get('token'):
                    st.session_state['final_token'] = data['token']
                    st.rerun()
                elif data.get('errors'):
                    st.error(f"Erreur SignIn : {data['errors'][0]['message']}")
            else:
                st.error("La réponse 'signIn' est vide (None). Vérifie tes identifiants.")

# (Garde le reste du code pour l'étape 2 OTP tel quel)
