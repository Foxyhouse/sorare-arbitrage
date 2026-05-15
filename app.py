import streamlit as st
import requests
import bcrypt

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

def get_latest_market_flux_optimized(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # 1. On récupère les 200 dernières offres (Flux massif)
    query_flux = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 200) {
          nodes {
            senderSide {
              anyCards {
                rarityTyped
                player { displayName slug }
              }
            }
            receiverSide { amounts { eurCents } }
          }
        }
      }
    }
    """
    try:
        res = requests.post(API_URL, json={'query': query_flux}, headers=headers).json()
        all_offers = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        rare_findings = []
        for offer in all_offers:
            cards = offer.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            card = cards[0]
            if card.get('rarityTyped') == 'rare':
                rare_findings.append({
                    "name": card.get('player', {}).get('displayName'),
                    "slug": card.get('player', {}).get('slug'),
                    "rare_price": float(offer.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                })
        
        if not rare_findings: return []

        # 2. On récupère TOUS les floors Limited en UNE SEULE REQUÊTE (Aliasing)
        # On limite aux 15 premières Rares trouvées pour ne pas faire exploser la requête
        rare_findings = rare_findings[:15] 
        alias_query = "query GetFloors { "
        for i, item in enumerate(rare_findings):
            alias_query += f'f{i}: tokens {{ liveSingleSaleOffers(playerSlug: "{item["slug"]}", rarities: [limited], first: 1) {{ nodes {{ receiverSide {{ amounts {{ eurCents }} }} }} }} }} '
        alias_query += " }"
        
        res_floors = requests.post(API_URL, json={'query': alias_query}, headers=headers).json()
        floors_data = res_floors.get('data', {})

        for i, item in enumerate(rare_findings):
            nodes = floors_data.get(f'f{i}', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
            if nodes:
                item['lim_price'] = float(nodes[0]['receiverSide']['amounts']['eurCents']) / 100
            else:
                item['lim_price'] = None
                
        return rare_findings
    except: return []

# --- UI STREAMLIT ---
st.set_page_config(page_title="Scanner 200", page_icon="⚡", layout="wide")
st.title("⚡ Scanner Haute Intensité (Top 200)")

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
    if st.button("🔄 Scanner les 200 derniers mouvements"): st.rerun()

    with st.spinner("Analyse profonde du marché (200 derniers items)..."):
        data = get_latest_market_flux_optimized(st.session_state['token'])
    
    if not data:
        st.warning("Aucune Rare trouvée dans les 200 derniers mouvements.")
    else:
        st.success(f"Analyse terminée : {len(data)} cartes Rares trouvées.")

    for item in data:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 2])
        c1.markdown(f"**{item['name']}**")
        c2.write(f"Rare: {item['rare_price']:.2f}€")
        if item['lim_price']:
            c3.write(f"Lim: {item['lim_price']:.2f}€")
            ratio = item['rare_price'] / item['lim_price']
            if ratio < 4.0: c4.success(f"🎯 RATIO TOP : {ratio:.2f}")
            else: c4.info(f"Ratio : {ratio:.2f}")
        else:
            c3.caption("Pas de Lim")
        st.divider()
