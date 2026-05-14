import streamlit as st
import requests
import bcrypt

API_URL = "https://api.sorare.com/graphql"

# 1. Fonction pour récupérer le sel (Salt)
def get_user_salt(email):
    res = requests.get(f"https://api.sorare.com/api/v1/users/{email}")
    if res.status_code == 200:
        return res.json().get("salt")
    return None

# 2. Fonction de connexion (Mutation officielle)
def sorare_sign_in(email, hashed_password=None, otp_attempt=None, otp_session_challenge=None):
    query = """
    mutation SignInMutation($input: signInInput!) {
      signIn(input: $input) {
        jwtToken(aud: "sorare-app") {
          token
        }
        otpSessionChallenge
        errors { message }
      }
    }
    """
    # Construction de l'input selon la doc
    if otp_session_challenge:
        input_data = {
            "otpSessionChallenge": otp_session_challenge,
            "otpAttempt": otp_attempt # La doc dit 'otpAttempt'
        }
    else:
        input_data = {
            "email": email,
            "password": hashed_password
        }

    response = requests.post(API_URL, json={'query': query, 'variables': {"input": input_data}})
    return response.json()

# --- INTERFACE ---
st.title("⚽ Sorare Auth (Conforme GitHub Doc)")

if 'final_token' not in st.session_state: st.session_state['final_token'] = None
if 'otp_challenge' not in st.session_state: st.session_state['otp_challenge'] = None

# ÉTAPE 1 : Email + Password (Hashé)
if not st.session_state['otp_challenge'] and not st.session_state['final_token']:
    with st.form("login"):
        u_email = st.text_input("Email")
        u_pass = st.text_input("Mot de passe", type="password")
        if st.form_submit_button("Se connecter"):
            # A. Récupérer le sel
            salt = get_user_salt(u_email)
            if salt:
                # B. Hasher le mot de passe (Important !)
                hashed_pw = bcrypt.hashpw(u_pass.encode('utf-8'), salt.encode('utf-8')).decode('utf-8')
                
                # C. Envoyer la mutation
                res = sorare_sign_in(u_email, hashed_password=hashed_pw)
                data = res.get('data', {}).get('signIn', {})
                
                if data.get('otpSessionChallenge'):
                    st.session_state['otp_challenge'] = data['otpSessionChallenge']
                    st.session_state['temp_email'] = u_email
                    st.rerun()
                elif data.get('jwtToken'):
                    st.session_state['final_token'] = data['jwtToken']['token']
                    st.rerun()
                else:
                    st.error(data.get('errors', [{}])[0].get('message', "Erreur inconnue"))
            else:
                st.error("Utilisateur introuvable.")

# ÉTAPE 2 : OTP (2FA)
elif st.session_state['otp_challenge'] and not st.session_state['final_token']:
    otp_code = st.text_input("Code 2FA (6 chiffres)")
    if st.button("Valider"):
        res = sorare_sign_in(st.session_state['temp_email'], otp_attempt=otp_code, otp_session_challenge=st.session_state['otp_challenge'])
        data = res.get('data', {}).get('signIn', {})
        if data.get('jwtToken'):
            st.session_state['final_token'] = data['jwtToken']['token']
            st.rerun()
        else:
            st.error("Code invalide.")

# ÉTAPE 3 : Dashboard (Une fois connecté)
if st.session_state['final_token']:
    st.success("✅ Connecté avec succès !")
    
    # Configuration des headers selon la doc GitHub
    # Note : la doc exige le header JWT-AUD identique à celui utilisé lors du login
    headers = {
        "Authorization": f"Bearer {st.session_state['final_token']}",
        "JWT-AUD": "sorare-app",
        "Content-Type": "application/json"
    }

     pour {name}. Vérifie si des cartes sont en vente.") 
            def get_market_data(slug):
        # Utilisation du fragment '... on Player' pour accéder au champ cards
        query = """
        query GetFloorPrices($slugs: [String!]!) {
          players(slugs: $slugs) {
            ... on Player {
              displayName
              cards(rarities: [limited, rare], first: 50) {
                nodes {
                  rarity
                  onSale
                  priceEur: amountNextStep { eur }
                }
              }
            }
          }
        }
        """
        try:
            response = requests.post(API_URL, json={'query': query, 'variables': {'slugs': [slug]}}, headers=headers)
            res_json = response.json()
            
            if "errors" in res_json:
                st.error(f"Erreur API : {res_json['errors'][0]['message']}")
                return None, None

            players_list = res_json.get('data', {}).get('players', [])
            if not players_list or players_list[0] is None:
                return None, None
            
            player_data = players_list[0]
            # On vérifie que player_data n'est pas vide (cas du fragment non trouvé)
            if not player_data.get('cards'):
                return None, None
                
            cards = player_data['cards'].get('nodes', [])
            
            # Extraction propre des prix
            lim_prices = []
            rare_prices = []
            
            for c in cards:
                if c.get('onSale') and c.get('priceEur'):
                    val = c['priceEur'].get('eur')
                    if val:
                        if c['rarity'] == 'limited':
                            lim_prices.append(val)
                        elif c['rarity'] == 'rare':
                            rare_prices.append(val)
            
            p_lim = min(lim_prices) if lim_prices else None
            p_rare = min(rare_prices) if rare_prices else None
            
            return p_lim, p_rare
        except Exception as e:
            return None, None

    # --- TON MONITORING ---
    st.divider()
    st.subheader("🕵️‍♂️ Opportunités d'Arbitrage en Direct")
    
    targets = {
        "Hervé Koffi": "kouakou-herve-koffi", 
        "Jordan Lefort": "jordan-lefort"
    }

    for name, slug in targets.items():
        p_lim, p_rare = get_market_data(slug)
        
        if p_lim is not None and p_rare is not None:
            ratio = p_rare / p_lim
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            with col1: st.markdown(f"**{name}**")
            with col2: st.write(f"{p_lim}€")
            with col3: st.write(f"{p_rare}€")
            with col4:
                if ratio < 4.0:
                    st.success(f"🔥 Ratio: {ratio:.2f}")
                else:
                    st.info(f"⚖️ Ratio: {ratio:.2f}")
        else:
            st.warning(f"⏳ Pas de prix (Buy Now) pour {name}. Vérifie si des cartes sont en vente.")
    
    # Création d'un tableau propre
    for name, slug in targets.items():
        p_lim, p_rare = get_market_data(slug)
        
        if p_lim and p_rare:
            ratio = p_rare / p_lim
            
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            with col1:
                st.markdown(f"**{name}**")
            with col2:
                st.write(f"L: {p_lim}€")
            with col3:
                st.write(f"R: {p_rare}€")
            with col4:
                # La règle d'or : Gain x4 / Prix < x4
                if ratio < 4.0:
                    st.success(f"🔥 Ratio: {ratio:.2f} | ACHÈTE RARE")
                else:
                    st.info(f"⚖️ Ratio: {ratio:.2f} | Reste en Limited")
        else:
            st.error(f"Données indisponibles pour {name}")

    if st.button("Se déconnecter"):
        st.session_state['final_token'] = None
        st.session_state['otp_challenge'] = None
        st.rerun()
