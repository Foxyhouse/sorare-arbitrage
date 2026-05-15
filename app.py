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

def run_audit_query(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # REQUÊTE MISE À JOUR : 'anyPlayer' au lieu de 'player' [Source: AnyCardInterface schema]
    # On filtre sur FOOTBALL pour plus de pertinence
    query = """
    query AuditMarket {
      tokens {
        liveSingleSaleOffers(first: 50, sport: FOOTBALL) {
          nodes {
            senderSide {
              anyCards {
                slug
                rarityTyped
                anyPlayer { 
                  displayName 
                  slug
                }
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
        response = requests.post(API_URL, json={'query': query}, headers=headers)
        res_json = response.json()
        st.session_state['full_api_response'] = res_json
        
        if "errors" in res_json:
            return [], f"Erreur API : {res_json['errors'][0]['message']}"
            
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        raw_list = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if cards:
                c = cards[0]
                player_info = c.get('anyPlayer', {}) # Correction ici
                raw_list.append({
                    "Date": n.get('createdAt'),
                    "Joueur": player_info.get('displayName', 'N/A'),
                    "Slug Joueur": player_info.get('slug', 'N/A'),
                    "Rareté": c.get('rarityTyped'),
                    "Prix (€)": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        return raw_list, None
    except Exception as e:
        return [], f"Erreur : {str(e)}"

# --- UI STREAMLIT ---
st.set_page_config(page_title="Audit Flux Sorare", layout="wide")
st.title("🔎 Audit du Flux de Marché Football")

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
    if st.button("🔄 Actualiser le flux"):
        st.rerun()

    data, error_msg = run_audit_query(st.session_state['token'])
    
    if error_msg:
        st.error(error_msg)
    elif data:
        st.success(f"{len(data)} dernières offres détectées")
        df = pd.DataFrame(data)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Aucune offre trouvée à cet instant.")

    if st.checkbox("⚙️ Voir JSON Brut"):
        st.json(st.session_state.get('full_api_response'))
