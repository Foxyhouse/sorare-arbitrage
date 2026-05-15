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

def scan_arbitrage_live_200(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # 1. On capture les 200 dernières offres FOOTBALL
    query_flux = """
    query GetLiveFlux200 {
      tokens {
        liveSingleSaleOffers(first: 200, sport: FOOTBALL) {
          nodes {
            senderSide {
              anyCards {
                rarityTyped
                anyPlayer { displayName slug }
              }
            }
            receiverSide { amounts { eurCents } }
            startDate
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query_flux}, headers=headers).json()
        nodes = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        rare_findings = []
        for n in nodes:
            cards = n.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            card = cards[0]
            if card.get('rarityTyped') == 'rare':
                rare_findings.append({
                    "Date": n.get('startDate'),
                    "name": card.get('anyPlayer', {}).get('displayName'),
                    "slug": card.get('anyPlayer', {}).get('slug'),
                    "rare_price": float(n.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        
        if not rare_findings: return []

        # 2. Requête groupée pour les Floors Limited (Aliasing)
        # On limite aux 20 premières Rares trouvées pour la stabilité
        rare_findings = rare_findings[:20]
        alias_query = "query GetFloors { "
        for i, item in enumerate(rare_findings):
            alias_query += f'f{i}: tokens {{ liveSingleSaleOffers(playerSlug: "{item["slug"]}", rarities: [limited], first: 1) {{ nodes {{ receiverSide {{ amounts {{ eurCents }} }} }} }} }} '
        alias_query += " }"
        
        res_floors = requests.post(API_URL, json={'query': alias_query}, headers=headers).json()
        floors_data = res_floors.get('data', {})

        final_data = []
        for i, item in enumerate(rare_findings):
            nodes_lim = floors_data.get(f'f{i}', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
            lim_floor = float(nodes_lim[0]['receiverSide']['amounts']['eurCents']) / 100 if nodes_lim else None
            
            ratio = item['rare_price'] / lim_floor if lim_floor else None
            
            final_data.append({
                "Mise en ligne": item['Date'],
                "Joueur": item['name'],
                "Prix Rare (€)": item['rare_price'],
                "Floor Limited (€)": lim_floor,
                "Ratio": round(ratio, 2) if ratio else "N/A"
            })
            
        return final_data
    except Exception as e:
        return []

# --- UI ---
st.set_page_config(page_title="Arbitrage Scanner 200", layout="wide")
st.title("🔥 Scanner d'Arbitrage (Top 200 Mouvements)")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Lancer le Scanner 200"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.sidebar.button("🔄 Scanner les 200 derniers"): st.rerun()

    with st.spinner("Analyse profonde des 200 dernières annonces..."):
        data = scan_arbitrage_live_200(st.session_state['token'])
    
    if data:
        df = pd.DataFrame(data)
        def color_ratio(val):
            try:
                if float(val) < 4.0: return 'background-color: #d4edda; color: #155724; font-weight: bold'
            except: pass
            return ''
            
        st.dataframe(df.style.applymap(color_ratio, subset=['Ratio']), use_container_width=True)
    else:
        st.warning("Aucune carte Rare trouvée dans les 200 derniers mouvements.")
