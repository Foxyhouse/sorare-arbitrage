import streamlit as st
import requests
import bcrypt
import pandas as pd

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

def get_raw_flux_200(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On demande les 200 dernières offres brutes
    query = """
    query GetMarketFlux200 {
      tokens {
        liveSingleSaleOffers(first: 200) {
          nodes {
            senderSide {
              anyCards {
                slug
                rarityTyped
                player { displayName }
              }
            }
            receiverSide { amounts { eurCents } }
            createdAt
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        raw_list = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards:
                c = cards[0]
                raw_list.append({
                    "Date": n.get('createdAt'),
                    "Joueur": c.get('player', {}).get('displayName'),
                    "Slug": c.get('slug'),
                    "Rareté": c.get('rarityTyped'),
                    "Prix (€)": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        return raw_list
    except: return []

# --- UI ---
st.set_page_config(page_title="Vérification Flux 200", layout="wide")
st.title("🔎 Audit du Flux de Marché (Top 200)")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    # Bloc de connexion simplifié
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Extraire les 200"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.button("🔄 Rafraîchir les données"):
        st.rerun()

    with st.spinner("Récupération des 200 dernières offres..."):
        data = get_raw_flux_200(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data)
        
        # Statistiques rapides
        st.info(f"Nombre d'offres récupérées : {len(df)}")
        st.write("Répartition par rareté :", df['Rareté'].value_counts())
        
        # Affichage du tableau interactif
        st.dataframe(df, use_container_width=True, height=600)
    else:
        st.error("Aucune donnée n'a pu être extraite. Vérifie la console ou le debug.")
