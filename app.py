import streamlit as st
import requests
import bcrypt
import pandas as pd
import json

# --- CONFIGURATION API ---
API_URL = "https://api.sorare.com/graphql"
AUDIENCE = "sorare-app"

def get_user_salt(email):
    try:
        res = requests.get(f"https://api.sorare.com/api/v1/users/{email}", timeout=5)
        return res.json().get("salt") if res.status_code == 200 else None
    except: return None

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
    input_data = {"otpSessionChallenge": otp_session_challenge, "otpAttempt": otp_attempt} if otp_session_challenge else {"email": email, "password": hashed_password}
    return requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}}).json()

def run_audit_query(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On tente une requête ultra-basique pour voir ce qui sort du tuyau
    query = """
    query AuditMarket {
      tokens {
        liveSingleSaleOffers(first: 50) {
          nodes {
            senderSide {
              anyCards {
                slug
                rarityTyped
                player { displayName }
              }
            }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query}, headers=headers)
        res_json = response.json()
        
        # STOCKAGE DU DEBUG BRUT
        st.session_state['full_api_response'] = res_json
        
        if "errors" in res_json:
            return [], f"L'API a renvoyé une erreur : {res_json['errors'][0]['message']}"
            
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        if not nodes:
            return [], "La requête a réussi mais la liste 'nodes' est vide (0 offre trouvée)."

        raw_list = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards:
                c = cards[0]
                raw_list.append({
                    "Joueur": c.get('player', {}).get('displayName', 'N/A'),
                    "Slug": c.get('slug'),
                    "Rareté": c.get('rarityTyped'),
                    "Prix (€)": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        return raw_list, None
    except Exception as e:
        return [], f"Erreur de connexion : {str(e)}"

# --- UI ---
st.set_page_config(page_title="Audit Debug Sorare", layout="wide")
st.title("🔎 Audit Force Brute du Marché")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Lancer l'audit"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    st.sidebar.button("🔄 Forcer Refresh", on_click=lambda: st.rerun())
    
    with st.status("Interrogation de l'API Sorare...") as status:
        data, error_msg = run_audit_query(st.session_state['token'])
        if error_msg:
            status.update(label="Échec de l'audit", state="error")
            st.error(error_msg)
        else:
            status.update(label="Audit réussi", state="complete")

    if data:
        st.success(f"Capture de {len(data)} offres en cours")
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)
    
    # ZONE DE DEBUG CRITIQUE
    st.divider()
    st.subheader("🛠️ Console de diagnostic (JSON Brut)")
    if 'full_api_response' in st.session_state:
        st.write("Dernière réponse reçue du serveur :")
        st.json(st.session_state['full_api_response'])
    else:
        st.info("Aucune réponse JSON stockée pour le moment.")

    # Tentative d'explication si vide
    if not data and not error_msg:
        st.warning("""
        ### Pourquoi c'est vide ?
        L'API Sorare semble restreindre l'accès à `liveSingleSaleOffers` sans paramètres plus précis (comme un sport ou un dictionnaire de slugs). 
        
        **Regarde bien le JSON en bas :** - Si tu vois `data: { tokens: { liveSingleSaleOffers: { nodes: [] } } }`, c'est que Sorare bloque le flux "anonyme" global.
        """)
