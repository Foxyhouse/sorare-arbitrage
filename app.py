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

def get_live_market_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # Requête focalisée sur le MARCHÉ LIVE (liveSingleSaleOffers)
    query = """
    query GetLiveMarket {
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
            receiverSide { 
              amounts { 
                eurCents 
              } 
            }
            startDate
          }
        }
      }
    }
    """
    try:
        response = requests.post(API_URL, json={'query': query}, headers=headers)
        res_json = response.json()
        st.session_state['full_api_response'] = res_json
        
        nodes = res_json.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        raw_list = []
        for n in nodes:
            # On vérifie la présence du prix en Euros
            eur_cents = n.get('receiverSide', {}).get('amounts', {}).get('eurCents')
            
            # Dans le marché live, si eur_cents est None, c'est peut-être une offre en ETH pur ou une erreur de data
            if eur_cents is not None:
                cards = n.get('senderSide', {}).get('anyCards', [])
                if cards:
                    c = cards[0]
                    player_info = c.get('anyPlayer', {})
                    raw_list.append({
                        "Mise en ligne": n.get('startDate'),
                        "Joueur": player_info.get('displayName', 'N/A'),
                        "Rareté": c.get('rarityTyped'),
                        "Prix (€)": float(eur_cents) / 100,
                        "Slug Joueur": player_info.get('slug', 'N/A')
                    })
        return raw_list
    except Exception as e:
        st.error(f"Erreur flux : {e}")
        return []

# --- UI ---
st.set_page_config(page_title="Flux Marché Live", layout="wide")
st.title("⚽ Marché Live : Dernières annonces (Ventes directes)")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Accéder au Marché Live"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.sidebar.button("🔄 Rafraîchir le flux"):
        st.rerun()
        
    data = get_live_market_flux(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data)
        # Tri par date de mise en ligne (la plus récente en haut)
        df = df.sort_values(by="Mise en ligne", ascending=False)
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("En attente de nouvelles offres sur le marché...")

    if st.checkbox("⚙️ Debug JSON Brut"):
        st.json(st.session_state.get('full_api_response'))
