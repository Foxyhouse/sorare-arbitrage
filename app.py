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

def get_latest_market_flux(jwt_token):
    headers = {"Authorization": f"Bearer {jwt_token}", "JWT-AUD": AUDIENCE, "Content-Type": "application/json"}
    
    # On demande les 50 dernières offres (flux global) pour être sûr d'avoir des Rares dedans
    query = """
    query GetMarketFlux {
      tokens {
        liveSingleSaleOffers(first: 50) {
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
        res = requests.post(API_URL, json={'query': query}, headers=headers).json()
        all_offers = res.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
        
        rare_findings = []
        for offer in all_offers:
            cards = offer.get('senderSide', {}).get('anyCards', [])
            if not cards: continue
            
            card = cards[0]
            # On ne garde que les RARES
            if card.get('rarityTyped') == 'rare':
                player_name = card.get('player', {}).get('displayName')
                player_slug = card.get('player', {}).get('slug')
                rare_price = float(offer.get('receiverSide', {}).get('amounts', {}).get('eurCents', 0)) / 100
                
                # Récupération flash du floor Limited pour ce joueur
                q_lim = """
                query GetLim($s: String!) {
                  tokens {
                    liveSingleSaleOffers(playerSlug: $s, rarities: [limited], first: 1) {
                      nodes { receiverSide { amounts { eurCents } } }
                    }
                  }
                }
                """
                res_lim = requests.post(API_URL, json={'query': q_lim, 'variables': {'s': player_slug}}, headers=headers).json()
                lim_nodes = res_lim.get('data', {}).get('tokens', {}).get('liveSingleSaleOffers', {}).get('nodes', [])
                
                min_lim = None
                if lim_nodes:
                    min_lim = float(lim_nodes[0]['receiverSide']['amounts']['eurCents']) / 100

                rare_findings.append({
                    "name": player_name,
                    "rare_price": rare_price,
                    "lim_price": min_lim
                })
                if len(rare_findings) >= 10: break # On s'arrête à 10
                
        return rare_findings
    except: return []

# --- UI ---
st.set_page_config(page_title="Scanner Live", page_icon="⚡")
st.title("⚡ Flux Live : Dernières Rares vs Floor Limited")

if 'token' not in st.session_state: st.session_state['token'] = None

if not st.session_state['token']:
    with st.form("login"):
        e = st.text_input("Email", value="jacques.troispoils@gmail.com")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Lancer le Scanner"):
            salt = get_user_salt(e)
            if salt:
                hp = bcrypt.hashpw(p.encode(), salt.encode()).decode()
                res = sorare_sign_in(e, hp)
                if res.get('data', {}).get('signIn', {}).get('jwtToken'):
                    st.session_state['token'] = res['data']['signIn']['jwtToken']['token']
                    st.rerun()
else:
    if st.button("🔄 Actualiser le flux"): st.rerun()

    with st.spinner("Analyse du flux de marché en cours..."):
        data = get_latest_market_flux(st.session_state['token'])
    
    if not data:
        st.warning("Aucune offre Rare détectée dans les 50 derniers mouvements de marché. Réessaie dans quelques secondes.")
    
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
